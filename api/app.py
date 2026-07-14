#api/app.py

import os
import sys
import json
import logging
import uuid
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path

import cv2
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

app = connexion.App(__name__, specification_dir=str(BASE_DIR / "config"))
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

def upload_image_and_process():
    """
    Connexion/OpenAPI maps an endpoint in openapi.yml to this handler.
    Expected multipart/form-data with key: 'image'
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

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from process_image import analyze_image, PIPELINE_NAME, PIPELINE_VERSION, SCHEMA_VERSION

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(analyze_image, str(upload_path))
            result = future.result(timeout=PROCESS_TIMEOUT_S)
    except concurrent.futures.TimeoutError:
        logging.error("job_id=%s Pipeline timed out after %ss", job_id, PROCESS_TIMEOUT_S)
        return jsonify({"error": "Processing timed out", "job_id": job_id}), 504
    except Exception:
        logging.exception("job_id=%s Pipeline raised an exception", job_id)
        return jsonify({"error": "Pipeline failed", "job_id": job_id}), 500

    # Write overlay image to results dir
    composite_image_name = f"{stem}_ResultImage_{job_id}.png"
    composite_image_path = RESULTS_DIR / composite_image_name
    cv2.imwrite(str(composite_image_path), result["overlay_img"])

    host_url_base = request.host_url.rstrip("/") + "/"
    composite_url = f"{host_url_base}download/{composite_image_name}"

    # Build canonical envelope
    payload = {
        "schema_version": SCHEMA_VERSION,
        "job_id": job_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pipeline": {"name": PIPELINE_NAME, "version": PIPELINE_VERSION},
        "input": {"image_filename": safe_name},
        "qc": result["qc"],
        "traits_emitted": result["traits_emitted"],
        "derived_images": [
            {"role": "overlay", "filename": composite_image_name, "url": composite_url}
        ],
        "objects": result["objects"],
    }

    logging.info("job_id=%s Analysis complete: %d objects", job_id, result["qc"]["object_count"])

    return jsonify(payload)

def main():
    logging.info("Starting app on http://0.0.0.0:8000")
    app.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
