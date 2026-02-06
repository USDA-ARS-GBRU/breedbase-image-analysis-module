#api/app.py

import os
import subprocess
import logging
import sys
import json
import uuid
from pathlib import Path

from flask import jsonify, request, send_from_directory
import connexion
from werkzeug.utils import secure_filename
from werkzeug.exceptions import BadRequest

# --- Paths / Folders ---
BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent

UPLOAD_DIR = REPO_ROOT / "uploads"
RESULTS_DIR = REPO_ROOT / "results"
LOG_DIR = REPO_ROOT / "logs"

UPLOAD_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# --- Logging Setup ---
LOG_FILE = LOG_DIR / "server.log"
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [app] %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)

# --- App Setup ---
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))  # template-friendly
PROCESS_TIMEOUT_S = int(os.getenv("PROCESS_TIMEOUT_S", "180"))

app = connexion.App(__name__, specification_dir=str(REPO_ROOT / "config"))
app.add_api("openapi.yml")
flask_app = app.app

# Hard limit for uploads (Flask enforces this)
flask_app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


@flask_app.route("/download/<path:filename>", methods=["GET"])
def download_file(filename):
    logging.info("Download requested: %s", filename)
    return send_from_directory(RESULTS_DIR, filename, as_attachment=False)


def _allowed_file(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS

def _to_breedbase_legacy(envelope: dict) -> dict:
    """
    Convert canonical envelope -> legacy BreedBase-compatible response.

    Output keys:
    - image_link (overlay image)
    - results (subanalyses)
    - info (optional qc metadata

    NOTE:
    - per-object image_link is null
    """

    # Overlay image URL (main analyzed image)
    image_link = None
    for di in envelope.get("derived_images", []) or []:
        if di.get("role") == "overlay" and di.get("url"):
            image_link = di["url"]
            break
    if not image_link and envelope.get("derived_images"):
        image_link = envelope["derived_images"][0].get("url")

    # Select emitted trait (POC = first trait)
    traits_emitted = envelope.get("traits_emitted") or []
    trait_key = traits_emitted[0] if traits_emitted else None

    results = {}

    objects = envelope.get("objects") or []
    for i, obj in enumerate(objects, start=1):
        sample_key = f"sample_{i:03d}"

        value = None
        if trait_key and isinstance(obj.get("traits"), dict):
            trait_block = obj["traits"].get(trait_key)
            if isinstance(trait_block, dict):
                value = trait_block.get("value")

        results[sample_key] = {
            "trait_value": value,
            "image_link": None
        }

    return {
        "image_link": image_link,
        "trait_name": trait_key,
        "results": results,
        "info": envelope.get("qc", {})
    }
    


def upload_image_and_process():
    """
    Connexion/OpenAPI maps an endpoint in openapi.yml to this handler.
    Expected multipart/form-data with key: 'image'

    Returns: JSON emitted by process_image.py on stdout.
    """
    # Use job id's to prevent filename collisions
    job_id = str(uuid.uuid4())

    logging.info("job_id=%s Received upload request", job_id)

    if "image" not in request.files:
        logging.warning("job_id=%s No file part in request", job_id)
        raise BadRequest("No file part named 'image' in multipart form.")

    file = request.files["image"]

    if not file.filename:
        logging.warning("job_id=%s Empty filename", job_id)
        raise BadRequest("Missing filename.")

    if not _allowed_file(file.filename):
        logging.warning("job_id=%s Disallowed extension filename=%r", job_id, file.filename)
        raise BadRequest(f"Invalid file type. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

    # Basic mimetype check
    if file.mimetype and not file.mimetype.startswith("image/"):
        logging.warning("job_id=%s Disallowed mimetype=%r", job_id, file.mimetype)
        raise BadRequest(f"Invalid mimetype: {file.mimetype}")

    safe_name = secure_filename(file.filename)
    stem = Path(safe_name).stem
    ext = Path(safe_name).suffix.lower()

    # Make upload filename unique to avoid collisions
    upload_name = f"{stem}_{job_id}{ext}"
    upload_path = UPLOAD_DIR / upload_name
    file.save(upload_path)
    logging.info("job_id=%s Saved upload to %s", job_id, upload_path)

    host_url = request.host_url.rstrip("/") + "/"

    cmd = [
        sys.executable,
        str(REPO_ROOT / "process_image.py"),
        str(upload_path),
        str(RESULTS_DIR),
        "--host_url",
        host_url,
    ]

    try:
        output_mode = request.args.get("output_mode")
        if output_mode in ("single", "all"):
            cmd.extend(["--output_mode", output_mode])
        marker_diameter = request.args.get("marker_diameter_in", type=float)
        if marker_diameter is not None:
            cmd.extend(["--marker_diameter_in", str(marker_diameter)])
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=PROCESS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        logging.exception("job_id=%s process_image.py timed out after %ss", job_id, PROCESS_TIMEOUT_S)
        return jsonify({"error": "Processing timed out", "job_id": job_id}), 504
    except Exception:
        logging.exception("job_id=%s Exception running process_image.py", job_id)
        return jsonify({"error": "Server error", "job_id": job_id}), 500

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    logging.info("job_id=%s returncode=%s", job_id, result.returncode)
    if stderr:
        logging.info("job_id=%s stderr=%r", job_id, stderr)

    if result.returncode != 0:
        # Keep response concise; stash full stderr in logs
        return jsonify({
            "error": "process_image failed",
            "job_id": job_id,
            "returncode": result.returncode,
        }), 500

    if not stdout:
        return jsonify({
            "error": "process_image returned no output",
            "job_id": job_id,
        }), 500

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        logging.error(
            "job_id=%s Invalid JSON from process_image stdout=%r", 
            job_id,
            stdout[:1000]
        )
        return jsonify({
            "error": "Invalid JSON from pipeline",
            "job_id": job_id,
        }), 500

    # Ensure job_id is always in the response
    if isinstance(payload, dict) and "job_id" not in payload:
        payload["job_id"] = job_id
        
    # Optional compatibility mode for single trait BreedBase output
    resp_format = (request.args.get("format") or "canonical").lower()
    
    if resp_format in ("breedbase", "bb", "legacy"):
        return jsonify(_to_breedbase_legacy(payload))

    return jsonify(payload)


if __name__ == "__main__":
    logging.info("Starting app on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000)
