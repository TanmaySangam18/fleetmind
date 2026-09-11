"""
Storage layer — replaces Storage Systems (block, object, file).

Files are chunked, encrypted with AES-256-GCM, and distributed across the device fleet.
Each chunk is assigned to a device (the device logically 'holds' it).
Chunks are physically stored on the backend filesystem under fleet_storage/.

Replication: each chunk is stored on min(replication_factor, fleet_size) devices.
This mirrors RAID across a phone fleet.

Encryption: each file gets a unique AES-256 key. The key is itself stored
(in plaintext for now — production would wrap with company key via KMS).
"""

import base64
import hashlib
import os
import uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CHUNK_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB chunks
STORAGE_BASE = Path("./fleet_storage")


def _storage_path(company_id: int, file_id: str, chunk_index: int, replica: int) -> Path:
    p = STORAGE_BASE / str(company_id) / file_id
    p.mkdir(parents=True, exist_ok=True)
    return p / f"chunk_{chunk_index:04d}_r{replica}.bin"


def store_file(company_id: int, filename: str, data: bytes, active_devices: list, db) -> dict:
    """
    Chunk, encrypt, and distribute a file across the phone fleet.
    Attempts to push each encrypted chunk directly to the device HTTP endpoint,
    and always keeps a local backend filesystem backup.
    Returns the stored file manifest.
    """
    import requests as _requests
    from database import StoredFile, StorageChunk

    if not active_devices:
        raise ValueError("No active devices to store file — fleet is empty")

    file_id = uuid.uuid4().hex
    file_key = os.urandom(32)  # AES-256 key for this file
    aesgcm = AESGCM(file_key)

    chunks = [data[i:i + CHUNK_SIZE_BYTES] for i in range(0, len(data), CHUNK_SIZE_BYTES)]
    if not chunks:
        chunks = [b""]

    replication_factor = min(2, len(active_devices))

    stored_file = StoredFile(
        company_id=company_id,
        file_id=file_id,
        filename=filename,
        total_size_bytes=len(data),
        chunk_count=len(chunks),
        replication_factor=replication_factor,
        encryption_key_b64=base64.b64encode(file_key).decode(),
    )
    db.add(stored_file)

    devices_used = set()

    for idx, chunk_data in enumerate(chunks):
        checksum = hashlib.sha256(chunk_data).hexdigest()
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, chunk_data, None)
        encrypted_blob = nonce + ciphertext

        for replica in range(replication_factor):
            device = active_devices[(idx + replica) % len(active_devices)]
            chunk_id = f"{file_id}_{idx:04d}_r{replica}"

            # Try to push to device directly
            pushed_to_device = False
            device_host = getattr(device, 'device_ip', None)
            if device_host:
                try:
                    resp = _requests.post(
                        f"http://{device_host}:11434/chunk/store",
                        json={
                            "chunk_id": chunk_id,
                            "data_b64": base64.b64encode(encrypted_blob).decode(),
                        },
                        timeout=10,
                    )
                    pushed_to_device = resp.status_code == 200
                except Exception:
                    pass

            # Always keep local backup (backend filesystem)
            path = _storage_path(company_id, file_id, idx, replica)
            path.write_bytes(encrypted_blob)

            db.add(StorageChunk(
                file_id=file_id,
                chunk_index=idx,
                device_id=device.device_id,
                storage_path=str(path),
                chunk_size_bytes=len(chunk_data),
                checksum=checksum,
                on_device=pushed_to_device,
            ))
            devices_used.add(device.device_id)

    db.commit()

    return {
        "file_id": file_id,
        "filename": filename,
        "size_bytes": len(data),
        "chunks": len(chunks),
        "replication_factor": replication_factor,
        "devices_used": list(devices_used),
    }


def retrieve_file(file_id: str, db) -> tuple:
    """
    Reassemble and decrypt a stored file. Returns (filename, plaintext_bytes).
    """
    from database import StoredFile, StorageChunk

    stored_file = db.query(StoredFile).filter(
        StoredFile.file_id == file_id,
        StoredFile.is_deleted == False,
    ).first()
    if not stored_file:
        raise FileNotFoundError(f"File {file_id} not found")

    file_key = base64.b64decode(stored_file.encryption_key_b64)
    aesgcm = AESGCM(file_key)

    # Fetch all replicas for each chunk and use the first readable one
    chunks_data = []
    for idx in range(stored_file.chunk_count):
        chunk_records = db.query(StorageChunk).filter(
            StorageChunk.file_id == file_id,
            StorageChunk.chunk_index == idx,
        ).all()
        if not chunk_records:
            raise RuntimeError(f"Missing chunk {idx} for file {file_id}")

        retrieved = False
        for chunk_record in chunk_records:
            path = Path(chunk_record.storage_path)
            if path.exists():
                raw = path.read_bytes()
                nonce, ciphertext = raw[:12], raw[12:]
                try:
                    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
                except Exception:
                    continue  # decryption failed — try next replica
                # Verify integrity
                if hashlib.sha256(plaintext).hexdigest() != chunk_record.checksum:
                    continue  # checksum mismatch — try next replica
                chunks_data.append(plaintext)
                retrieved = True
                break
        if not retrieved:
            raise RuntimeError(
                f"Chunk {idx} is unreadable on all replicas — data loss detected"
            )

    return stored_file.filename, b"".join(chunks_data)


def delete_file(file_id: str, company_id: int, db) -> bool:
    """Soft-delete a stored file and remove its chunk data from disk."""
    from database import StoredFile, StorageChunk

    stored_file = db.query(StoredFile).filter(
        StoredFile.file_id == file_id,
        StoredFile.company_id == company_id,
    ).first()
    if not stored_file:
        return False

    chunks = db.query(StorageChunk).filter(StorageChunk.file_id == file_id).all()
    for chunk in chunks:
        path = Path(chunk.storage_path)
        if path.exists():
            path.unlink()

    stored_file.is_deleted = True
    db.commit()
    return True


def fleet_storage_stats(company_id: int, db) -> dict:
    """Return aggregate storage statistics for a company's fleet."""
    from database import StoredFile

    files = db.query(StoredFile).filter(
        StoredFile.company_id == company_id,
        StoredFile.is_deleted == False,
    ).all()
    total_bytes = sum(f.total_size_bytes for f in files)
    return {
        "files_stored": len(files),
        "total_size_bytes": total_bytes,
        "total_size_mb": round(total_bytes / 1024 / 1024, 2),
    }
