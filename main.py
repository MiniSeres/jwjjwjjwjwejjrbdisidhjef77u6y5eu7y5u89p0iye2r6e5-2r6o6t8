from flask import Flask, render_template, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json, secrets, os, subprocess, re, time, tempfile, shutil
from datetime import datetime, timedelta
from functools import wraps
import bcrypt
import fcntl
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

DATA_FILE = "data.json"
SALT_ROUNDS = 12
MAX_CODE_SIZE = 1024 * 50
MAX_BOTS_PER_USER = 20
TOKEN_EXPIRY_HOURS = 24
ALLOWED_LANGUAGES = ["python", "javascript", "ruby", "cpp"]

app = Flask(__name__)
limiter = Limiter(app=app, key_func=get_remote_address, default_limits=["100 per minute"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
handler = RotatingFileHandler('app.log', maxBytes=10000, backupCount=3)
logger.addHandler(handler)

def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(SALT_ROUNDS)).decode()

def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())

def generate_token():
    return secrets.token_urlsafe(32)

def load_data():
    if not os.path.exists(DATA_FILE):
        default = {"users": {}, "bots": {}, "sessions": {}}
        save_data(default)
        return default
    with open(DATA_FILE, "r") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        data = json.load(f)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return data

def save_data(data):
    with open(DATA_FILE, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(data, f, indent=2)
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def auth_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('X-Token')
        if not token:
            return jsonify({"error": "Missing token"}), 401
        data = load_data()
        now = datetime.now().isoformat()
        for user, info in data["users"].items():
            if info.get("token") == token:
                expiry = info.get("token_expiry")
                if expiry and datetime.fromisoformat(expiry) < datetime.now():
                    info["token"] = None
                    save_data(data)
                    return jsonify({"error": "Token expired"}), 401
                info["token_expiry"] = (datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat()
                save_data(data)
                request.user = user
                return f(*args, **kwargs)
        return jsonify({"error": "Invalid token"}), 401
    return decorated

def run_in_docker(code, language, timeout=3):
    temp_dir = tempfile.mkdtemp()
    try:
        ext = {"python":"py", "javascript":"js", "ruby":"rb", "cpp":"cpp"}.get(language, "txt")
        code_file = Path(temp_dir) / f"code.{ext}"
        with open(code_file, "w") as f:
            f.write(code)
        
        if language == "cpp":
            subprocess.run(["g++", str(code_file), "-o", f"{temp_dir}/code"], capture_output=True, text=True, timeout=10)
            cmd = [f"{temp_dir}/code"]
        else:
            cmd = {"python": ["python3", str(code_file)], "javascript": ["node", str(code_file)], "ruby": ["ruby", str(code_file)]}.get(language)
        
        result = subprocess.run(
            ["timeout", str(timeout), *cmd],
            capture_output=True,
            text=True,
            cwd=temp_dir,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "PYTHONPATH": ""}
        )
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "Execution timeout"
    except Exception as e:
        return f"Error: {e}"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def sanitize_filename(name):
    return re.sub(r'[^a-zA-Z0-9_-]', '', name)

def update_stats():
    data = load_data()
    total = len(data.get("bots", {}))
    online = sum(1 for b in data["bots"].values() if b.get("status") == "on")
    data["stats"] = {"total": total, "online": online, "last_update": datetime.now().isoformat()}
    save_data(data)

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/register', methods=['POST'])
@limiter.limit("5 per hour")
def api_register():
    data = load_data()
    username = request.json.get('username')
    password = request.json.get('password')
    if not username or not password or len(password) < 6:
        return jsonify({"error": "Invalid input"}), 400
    if username in data["users"]:
        return jsonify({"error": "User exists"}), 400
    token = generate_token()
    data["users"][username] = {
        "password": hash_password(password),
        "token": token,
        "token_expiry": (datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat(),
        "created": datetime.now().isoformat()
    }
    save_data(data)
    logger.info(f"User registered: {username}")
    return jsonify({"success": True, "username": username, "token": token})

@app.route('/api/login', methods=['POST'])
@limiter.limit("10 per minute")
def api_login():
    data = load_data()
    username = request.json.get('username')
    password = request.json.get('password')
    user = data["users"].get(username)
    if not user or not verify_password(password, user["password"]):
        logger.warning(f"Failed login: {username}")
        return jsonify({"error": "Invalid"}), 401
    token = generate_token()
    user["token"] = token
    user["token_expiry"] = (datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat()
    save_data(data)
    logger.info(f"User logged in: {username}")
    return jsonify({"success": True, "username": username, "token": token})

@app.route('/api/verify')
def api_verify():
    token = request.headers.get('X-Token')
    if not token:
        return jsonify({"valid": False})
    data = load_data()
    for user, info in data["users"].items():
        if info.get("token") == token:
            expiry = info.get("token_expiry")
            if expiry and datetime.fromisoformat(expiry) < datetime.now():
                return jsonify({"valid": False, "expired": True})
            return jsonify({"valid": True, "username": user})
    return jsonify({"valid": False})

@app.route('/api/refresh', methods=['POST'])
@auth_required
def api_refresh():
    data = load_data()
    user = data["users"].get(request.user)
    if not user:
        return jsonify({"error": "User not found"}), 404
    token = generate_token()
    user["token"] = token
    user["token_expiry"] = (datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)).isoformat()
    save_data(data)
    return jsonify({"success": True, "token": token})

@app.route('/api/bots')
@auth_required
def api_bots():
    data = load_data()
    user_bots = {name: bot for name, bot in data["bots"].items() if bot["owner"] == request.user}
    for bot in user_bots.values():
        bot['token'] = '***HIDDEN***'
    return jsonify(user_bots)

@app.route('/api/bots', methods=['POST'])
@auth_required
@limiter.limit("5 per minute")
def api_create_bot():
    data = load_data()
    user_bots = [b for b in data["bots"].values() if b["owner"] == request.user]
    if len(user_bots) >= MAX_BOTS_PER_USER:
        return jsonify({"error": f"Max {MAX_BOTS_PER_USER} bots"}), 400
    
    name = sanitize_filename(request.json.get('name'))
    if not name or len(name) < 3:
        return jsonify({"error": "Invalid name"}), 400
    if name in data["bots"]:
        return jsonify({"error": "Exists"}), 400
    
    language = request.json.get('language', 'python')
    if language not in ALLOWED_LANGUAGES:
        return jsonify({"error": "Unsupported language"}), 400
    
    data["bots"][name] = {
        "owner": request.user,
        "username": sanitize_filename(request.json.get('username', f"{name}_bot")),
        "status": "off",
        "language": language,
        "token": "",
        "created": datetime.now().isoformat()
    }
    save_data(data)
    os.makedirs("bots", exist_ok=True)
    ext = {"python":"py", "javascript":"js", "ruby":"rb", "cpp":"cpp"}.get(language, "txt")
    with open(f"bots/{name}.{ext}", "w") as f:
        f.write(f"# {name} code\n")
    update_stats()
    logger.info(f"Bot created: {name} by {request.user}")
    return jsonify({"success": True})

@app.route('/api/bots/<bot_name>', methods=['POST'])
@auth_required
def api_bot_action(bot_name):
    data = load_data()
    bot_name = sanitize_filename(bot_name)
    bot = data["bots"].get(bot_name)
    if not bot or bot["owner"] != request.user:
        return jsonify({"error": "Not found"}), 404
    
    action = request.json.get('action')
    if action == "toggle":
        bot["status"] = "off" if bot["status"] == "on" else "on"
        logger.info(f"Bot {bot_name} toggled to {bot['status']} by {request.user}")
    elif action == "delete":
        del data["bots"][bot_name]
        for f in Path("bots").glob(f"{bot_name}.*"):
            f.unlink(missing_ok=True)
        logger.info(f"Bot deleted: {bot_name} by {request.user}")
    elif action == "rename":
        new_name = sanitize_filename(request.json.get('new_name'))
        if new_name and new_name not in data["bots"]:
            data["bots"][new_name] = data["bots"].pop(bot_name)
            for f in Path("bots").glob(f"{bot_name}.*"):
                ext = f.suffix
                f.rename(Path(f"bots/{new_name}{ext}"))
            logger.info(f"Bot renamed: {bot_name} -> {new_name} by {request.user}")
    save_data(data)
    update_stats()
    return jsonify({"success": True})

@app.route('/api/code/<bot_name>')
@auth_required
def api_get_code(bot_name):
    data = load_data()
    bot_name = sanitize_filename(bot_name)
    bot = data["bots"].get(bot_name)
    if not bot or bot["owner"] != request.user:
        return jsonify({"error": "Not found"}), 404
    
    language = bot.get("language", "python")
    ext = {"python":"py", "javascript":"js", "ruby":"rb", "cpp":"cpp"}.get(language, "txt")
    code_file = Path(f"bots/{bot_name}.{ext}")
    if not code_file.exists():
        return jsonify({"code": f"# {bot_name} code", "language": language})
    with open(code_file, "r") as f:
        code = f.read()
    if len(code) > MAX_CODE_SIZE:
        return jsonify({"error": "Code too large"}), 400
    return jsonify({"code": code, "language": language})

@app.route('/api/code/<bot_name>', methods=['POST'])
@auth_required
def api_save_code(bot_name):
    data = load_data()
    bot_name = sanitize_filename(bot_name)
    bot = data["bots"].get(bot_name)
    if not bot or bot["owner"] != request.user:
        return jsonify({"error": "Not found"}), 404
    
    code = request.json.get('code', '')
    if len(code) > MAX_CODE_SIZE:
        return jsonify({"error": "Code too large"}), 400
    
    language = request.json.get('language', 'python')
    if language not in ALLOWED_LANGUAGES:
        return jsonify({"error": "Unsupported language"}), 400
    
    token = request.json.get('token', '')
    bot["language"] = language
    bot["token"] = token
    save_data(data)
    ext = {"python":"py", "javascript":"js", "ruby":"rb", "cpp":"cpp"}.get(language, "txt")
    with open(f"bots/{bot_name}.{ext}", "w") as f:
        f.write(code)
    return jsonify({"success": True})

@app.route('/api/run/<bot_name>', methods=['POST'])
@auth_required
@limiter.limit("10 per minute")
def api_run_code(bot_name):
    data = load_data()
    bot_name = sanitize_filename(bot_name)
    bot = data["bots"].get(bot_name)
    if not bot or bot["owner"] != request.user:
        return jsonify({"error": "Not found"}), 404
    if bot.get("status") != "on":
        return jsonify({"error": "Bot offline"}), 400
    
    language = bot.get("language", "python")
    ext = {"python":"py", "javascript":"js", "ruby":"rb", "cpp":"cpp"}.get(language, "txt")
    code_file = Path(f"bots/{bot_name}.{ext}")
    if not code_file.exists():
        return jsonify({"error": "Code not found"}), 404
    
    try:
        with open(code_file, "r") as f:
            code = f.read()
        
        output = run_in_docker(code, language, timeout=3)
        logger.info(f"Code executed: {bot_name} by {request.user}")
        return jsonify({"output": output or "No output"})
    except Exception as e:
        logger.error(f"Execution error {bot_name}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/token/<bot_name>', methods=['POST'])
@auth_required
def api_update_token(bot_name):
    data = load_data()
    bot_name = sanitize_filename(bot_name)
    bot = data["bots"].get(bot_name)
    if not bot or bot["owner"] != request.user:
        return jsonify({"error": "Not found"}), 404
    bot["token"] = request.json.get('token', '')
    save_data(data)
    return jsonify({"success": True})

@app.route('/api/stats')
def api_stats():
    data = load_data()
    return jsonify(data.get("stats", {}))

@app.route('/api/logout', methods=['POST'])
def api_logout():
    token = request.headers.get('X-Token')
    if token:
        data = load_data()
        for user, info in data["users"].items():
            if info.get("token") == token:
                info["token"] = None
                info["token_expiry"] = None
                save_data(data)
                logger.info(f"User logged out: {user}")
                break
    return jsonify({"success": True})

if __name__ == "__main__":
    os.makedirs("bots", exist_ok=True)
    update_stats()
    app.run(host='0.0.0.0', port=5000, debug=False)
