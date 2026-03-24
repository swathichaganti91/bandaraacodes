from flask import Flask, request, jsonify
from flask_cors import CORS
import mysql.connector
import boto3
import uuid
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
CORS(app)

# ══════════════════════════════════════════════════════════════
#  DATABASE CONFIG  —  AWS RDS MySQL
# ══════════════════════════════════════════════════════════════
db_config = {
    'host':            'backend.ooo',  # 🔁 replace
    'user':            'admin',                                 # 🔁 replace
    'password':        'mandeep123',                     # 🔁 replace
    'database':        'dev',
    'port':            3306,
    'connect_timeout': 10,
}

def get_db():
    return mysql.connector.connect(**db_config)


# ══════════════════════════════════════════════════════════════
#  S3 CONFIG  —  PUBLIC bucket
# ══════════════════════════════════════════════════════════════
S3_BUCKET   = "mandu-bucket-mandu" #🔁 replace with your bucket name
S3_REGION   = "us-east-1"
S3_FOLDER   = "bandaara-images"  # optional folder prefix in bucket
S3_BASE_URL = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{S3_FOLDER}"

s3 = boto3.client("s3", region_name=S3_REGION)

# ── content-type → extension mapping (for files with no extension) ──
MIME_TO_EXT = {
    'image/jpeg':    'jpg',
    'image/jpg':     'jpg',
    'image/png':     'png',
    'image/webp':    'webp',
    'image/gif':     'gif',
    'image/heic':    'jpg',   # convert heic to jpg label
    'image/heif':    'jpg',
    'application/octet-stream': 'jpg',  # generic binary → default jpg
}
EXT_TO_MIME = {
    'jpg':  'image/jpeg',
    'jpeg': 'image/jpeg',
    'png':  'image/png',
    'webp': 'image/webp',
    'gif':  'image/gif',
}


# ══════════════════════════════════════════════════════════════
#  REGISTER
# ══════════════════════════════════════════════════════════════
@app.route('/register', methods=['POST'])
def register():
    data = request.json
    print(f"[REGISTER] {data}")

    if not data or not data.get('username') or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Missing required fields'}), 400

    hashed_pw = generate_password_hash(data['password'])

    conn = cursor = None
    try:
        conn   = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, email, password) VALUES (%s, %s, %s)",
            (data['username'].strip(), data['email'].strip().lower(), hashed_pw)
        )
        conn.commit()
        print(f"[REGISTER] OK: {data['email']}")
        return jsonify({'msg': 'Registered successfully'}), 201

    except mysql.connector.IntegrityError:
        return jsonify({'error': 'Email already registered'}), 409

    except Exception as e:
        print(f"[REGISTER ERROR] {e}")
        return jsonify({'error': 'Server error'}), 500

    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
#  LOGIN
# ══════════════════════════════════════════════════════════════
@app.route('/login', methods=['POST'])
def login():
    data = request.json
    print(f"[LOGIN] {data.get('email') if data else 'no data'}")

    if not data or not data.get('email') or not data.get('password'):
        return jsonify({'error': 'Missing credentials'}), 400

    conn = cursor = None
    try:
        conn   = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM users WHERE email = %s",
            (data['email'].strip().lower(),)
        )
        user = cursor.fetchone()

        if user and check_password_hash(user['password'], data['password']):
            print(f"[LOGIN] OK user_id={user['id']}")
            return jsonify({"user_id": user["id"], "username": user["username"]}), 200

        print("[LOGIN] Invalid credentials")
        return jsonify({"error": "Invalid email or password"}), 401

    except Exception as e:
        print(f"[LOGIN ERROR] {e}")
        return jsonify({'error': 'Server error'}), 500

    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
#  ADD BANDARA  —  S3 upload + RDS save
# ══════════════════════════════════════════════════════════════
@app.route('/bandara/add', methods=['POST'])
def add_bandara():
    print("=== /bandara/add ===")
    print("FILES:", request.files)
    print("FORM :", request.form)

    # ── 1. Check image exists ──
    if 'image' not in request.files:
        print("[ADD] FAIL: no image key")
        return jsonify({'error': 'No image provided'}), 400

    file = request.files['image']
    print(f"[ADD] filename='{file.filename}' content_type='{file.content_type}'")

    # ── 2. Check form fields ──
    location = request.form.get('location', '').strip()
    user_id  = request.form.get('user_id',  '').strip()
    print(f"[ADD] location='{location}' user_id='{user_id}'")

    if not location:
        print("[ADD] FAIL: no location")
        return jsonify({'error': 'Missing location'}), 400

    if not user_id:
        print("[ADD] FAIL: no user_id")
        return jsonify({'error': 'Missing user_id — please logout and login again'}), 400

    # ── 3. Determine file extension ──
    #  First try from filename, then fall back to content-type
    ext = ''
    if file.filename and '.' in file.filename:
        ext = file.filename.rsplit('.', 1)[-1].lower()

    if not ext or ext not in EXT_TO_MIME:
        # Try to get ext from content_type header
        content_type = file.content_type or ''
        ext = MIME_TO_EXT.get(content_type.split(';')[0].strip(), '')
        print(f"[ADD] ext from content_type '{content_type}' → '{ext}'")

    if not ext:
        ext = 'jpg'   # ultimate fallback — assume jpeg
        print("[ADD] no ext detected, defaulting to jpg")

    print(f"[ADD] final ext: '{ext}'")

    # ── 4. Build safe filename ──
    # Use uuid so it's always unique and safe
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    s3_key      = f"{S3_FOLDER}/{unique_name}"
    mime_type   = EXT_TO_MIME.get(ext, 'image/jpeg')

    print(f"[ADD] s3_key='{s3_key}' mime='{mime_type}'")

    # ── 5. Upload to S3 (PUBLIC READ) ──
    try:
        s3.upload_fileobj(
            file,
            S3_BUCKET,
            s3_key,
            ExtraArgs={
                "ContentType": mime_type,
                "ACL":         "public-read",
            }
        )
        image_url = f"{S3_BASE_URL}/{unique_name}"
        print(f"[ADD] S3 OK: {image_url}")

    except Exception as e:
        print(f"[ADD] S3 ERROR: {e}")
        return jsonify({'error': f'S3 upload failed: {str(e)}'}), 500

    # ── 6. Save to RDS ──
    conn = cursor = None
    try:
        conn   = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO bandara (user_id, image, location) VALUES (%s, %s, %s)",
            (user_id, image_url, location)
        )
        conn.commit()
        print(f"[ADD] DB OK: user_id={user_id}")
        return jsonify({"msg": "Uploaded successfully", "url": image_url}), 201

    except Exception as e:
        print(f"[ADD] DB ERROR: {e}")
        return jsonify({'error': f'DB save failed: {str(e)}'}), 500

    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
#  GET ALL BANDARA SIGHTINGS
# ══════════════════════════════════════════════════════════════
@app.route('/bandara', methods=['GET'])
def get_bandara():
    conn = cursor = None
    try:
        conn   = get_db()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM bandara ORDER BY id DESC")
        data = cursor.fetchall()
        print(f"[GET] {len(data)} records")
        return jsonify(data), 200

    except Exception as e:
        print(f"[GET ERROR] {e}")
        return jsonify({'error': 'Failed to fetch data'}), 500

    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ══════════════════════════════════════════════════════════════
@app.route('/health', methods=['GET'])
def health():
    try:
        conn = get_db()
        conn.close()
        return jsonify({"status": "ok", "db": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "error", "db": str(e)}), 500


# ══════════════════════════════════════════════════════════════
#  START
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
