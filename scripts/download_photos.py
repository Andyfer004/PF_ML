"""Copia autorizada de fotos del curso vía Databricks SQL, sin credenciales AWS locales."""
import argparse
import base64
import concurrent.futures
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "s3://cc3105-raw-869227452861-us-east-2-an/img/"


def api(method, path, payload=None):
    command = ["bash", str(ROOT / "scripts/databricks.sh"), "api", method, path,
               "--output", "json"]
    if payload is not None:
        command += ["--json", json.dumps(payload)]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def download_batch(records):
    pending = []
    for record in records:
        source = record["foto_origen"]
        if not source.startswith(SOURCE):
            raise ValueError("Origen ajeno al conjunto autorizado")
        relative = source[len(SOURCE):]
        if any(part in (".", "..") for part in relative.split("/")):
            raise ValueError("Ruta no permitida")
        destination = ROOT / "data/images" / relative
        if destination.exists() and destination.stat().st_size == record["bytes"]:
            continue
        pending.append((source, destination, record["bytes"]))
    if not pending:
        return 0
    statement = " UNION ALL ".join(
        "SELECT path, length, base64(content) FROM read_files('" + source.replace("'", "''")
        + "', format => 'binaryFile')" for source, _, _ in pending
    )
    response = api("post", "/api/2.0/sql/statements", {
        "warehouse_id": "4b28a3706d123886", "statement": statement,
        "wait_timeout": "10s", "on_wait_timeout": "CONTINUE", "row_limit": len(pending),
    })
    deadline = time.monotonic() + 300
    while response["status"]["state"] in ("PENDING", "RUNNING"):
        if time.monotonic() > deadline:
            raise TimeoutError("La descarga no terminó dentro de cinco minutos")
        time.sleep(2)
        response = api("get", "/api/2.0/sql/statements/" + response["statement_id"])
    if response["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(str(response["status"]))
    if response.get("manifest", {}).get("truncated"):
        raise RuntimeError("Resultado truncado: reducir tamaño de lote")
    rows = list(response.get("result", {}).get("data_array", []))
    chunk = response.get("result", {})
    while chunk.get("next_chunk_internal_link"):
        chunk = api("get", chunk["next_chunk_internal_link"])
        rows.extend(chunk.get("data_array", []))
    expected = {source: (destination, size) for source, destination, size in pending}
    if {row[0] for row in rows} != set(expected):
        raise RuntimeError("El lote no corresponde exactamente a las fotos solicitadas")
    for source, length, encoded in rows:
        destination, size = expected[source]
        # Spark entrega base64 MIME con saltos de línea.
        content = base64.b64decode("".join(encoded.split()), validate=True)
        if len(content) != int(length) or len(content) != size:
            raise RuntimeError("Tamaño de imagen no coincide con su metadata")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    records = json.loads((ROOT / "output/diagnostico_databricks.json").read_text())["metadata"]
    if not args.all:
        records = records[:args.limit]
    batches = [records[i:i+3] for i in range(0, len(records), 3)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        count = 0
        for copied in executor.map(download_batch, batches):
            count += copied
            print(f"Fotos copiadas: {count}", flush=True)
