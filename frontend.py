from flask import Flask, render_template, request, redirect, session, jsonify
import requests
import smtplib
import random
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

app = Flask(__name__)
app.secret_key = "bandaara_secret_2024"

# ── Backend Private IP ──
API = os.getenv("API_URL")

# ── Email Config ──
EMAIL_SENDER   = "nicomandu37@gmail.com"
EMAIL_PASSWORD = "yfih smaj ukrk pgjl"   # Gmail App Password

OTP_EXPIRY_SECONDS = 300   # 5 minutes


# ══════════════════════════════════════
# HELPER: Send OTP Email
# ══════════════════════════════════════
def send_otp_email(to_email, otp, username="there"):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🍽️ Your Bandaara Verification Code"
        msg["From"]    = EMAIL_SENDER
        msg["To"]      = to_email

        html = f"""
        <div style="font-family:'DM Sans',Arial,sans-serif;max-width:480px;margin:0 auto;background:#f5f3ef;padding:40px 20px;">
          <div style="background:#ffffff;border-radius:20px;padding:48px 40px;box-shadow:0 8px 32px rgba(0,0,0,0.08);">

            <div style="text-align:center;margin-bottom:32px;">
              <div style="font-size:2.5rem;margin-bottom:12px;">🍱</div>
              <h1 style="font-size:1.8rem;font-weight:700;color:#1a1a2e;margin:0;letter-spacing:-0.02em;">
                Bandaara Alert
              </h1>
              <p style="color:#8a8fa8;font-size:0.85rem;margin-top:4px;">Email Verification</p>
            </div>

            <p style="color:#1a1a2e;font-size:0.95rem;margin-bottom:8px;">
              Hi <strong>{username}</strong> 👋
            </p>
            <p style="color:#8a8fa8;font-size:0.88rem;line-height:1.6;margin-bottom:32px;">
              Use the verification code below to complete your registration.
              This code expires in <strong>5 minutes</strong>.
            </p>

            <div style="background:#f5f3ef;border-radius:14px;padding:28px;text-align:center;margin-bottom:32px;border:2px dashed rgba(79,124,255,0.2);">
              <p style="font-size:0.7rem;color:#8a8fa8;letter-spacing:0.1em;text-transform:uppercase;margin-bottom:12px;font-weight:600;">Your OTP Code</p>
              <div style="font-size:2.6rem;font-weight:700;color:#4f7cff;letter-spacing:0.18em;">{otp}</div>
            </div>

            <p style="color:#8a8fa8;font-size:0.78rem;text-align:center;line-height:1.6;">
              If you didn't create a Bandaara account, you can safely ignore this email.
            </p>

          </div>
          <p style="text-align:center;color:#b0b5c4;font-size:0.72rem;margin-top:20px;">
            © 2024 Bandaara Alert · Hyderabad, India
          </p>
        </div>
        """

        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        return False


def generate_otp():
    return str(random.randint(100000, 999999))


# ══════════════════════════════════════
# PAGES
# ══════════════════════════════════════
@app.route("/")
def login_page():
    if "user_id" in session:
        return redirect("/dashboard")
    return render_template("login.html")


@app.route("/register-page")
def register_page():
    return render_template("register.html")


@app.route("/verify-otp")
def otp_page():
    # Must have pending registration in session
    if "pending_email" not in session:
        return redirect("/register-page")
    return render_template("otp.html",
                           email=session.get("pending_email", ""),
                           username=session.get("pending_username", ""))


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/")
    try:
        res = requests.get(f"{API}/bandara", timeout=5)
        bandara = res.json()
    except:
        bandara = []
    return render_template("dashboard.html", bandara=bandara)


# ══════════════════════════════════════
# AUTH
# ══════════════════════════════════════
@app.route("/login", methods=["POST"])
def login():
    data = {
        "email":    request.form["email"],
        "password": request.form["password"]
    }
    try:
        res = requests.post(f"{API}/login", json=data, timeout=5)
        if res.status_code == 200:
            session["user_id"] = res.json()["user_id"]
            return redirect("/dashboard")
    except:
        pass
    return render_template("login.html", error="Invalid email or password. Please try again.")


@app.route("/register", methods=["POST"])
def register():
    username = request.form["username"]
    email    = request.form["email"]
    password = request.form["password"]

    # Save registration data in session (pending OTP verification)
    session["pending_username"] = username
    session["pending_email"]    = email
    session["pending_password"] = password

    # Generate and store OTP
    otp = generate_otp()
    session["otp"]            = otp
    session["otp_created_at"] = time.time()

    # Send OTP email
    sent = send_otp_email(email, otp, username)
    if not sent:
        return render_template("register.html",
                               error="Failed to send OTP. Please check your email and try again.")

    return redirect("/verify-otp")


@app.route("/verify-otp", methods=["POST"])
def verify_otp():
    entered_otp = request.form.get("otp", "").strip()

    # Check session
    if "otp" not in session or "pending_email" not in session:
        return redirect("/register-page")

    # Check expiry
    created_at = session.get("otp_created_at", 0)
    if time.time() - created_at > OTP_EXPIRY_SECONDS:
        session.pop("otp", None)
        return render_template("otp.html",
                               email=session.get("pending_email", ""),
                               username=session.get("pending_username", ""),
                               error="OTP has expired. Please register again.",
                               expired=True)

    # Check OTP match
    if entered_otp != session.get("otp"):
        return render_template("otp.html",
                               email=session.get("pending_email", ""),
                               username=session.get("pending_username", ""),
                               error="Incorrect OTP. Please try again.",
                               attempts_left=True)

    # OTP valid → register with backend
    data = {
        "username": session.pop("pending_username", ""),
        "email":    session.pop("pending_email", ""),
        "password": session.pop("pending_password", "")
    }
    session.pop("otp", None)
    session.pop("otp_created_at", None)

    try:
        requests.post(f"{API}/register", json=data, timeout=5)
    except:
        pass

    return redirect("/?registered=1")


@app.route("/resend-otp", methods=["POST"])
def resend_otp():
    if "pending_email" not in session:
        return redirect("/register-page")

    otp = generate_otp()
    session["otp"]            = otp
    session["otp_created_at"] = time.time()

    send_otp_email(
        session["pending_email"],
        otp,
        session.get("pending_username", "there")
    )

    return redirect("/verify-otp?resent=1")


# ══════════════════════════════════════
# BANDARA
# ══════════════════════════════════════
@app.route("/add-bandara", methods=["POST"])
def add_bandara():
    if "user_id" not in session:
        return redirect("/")
    files = {"image": request.files["image"]}
    data  = {
        "location": request.form["location"],
        "user_id":  session["user_id"]
    }
    try:
        requests.post(f"{API}/bandara/add", files=files, data=data, timeout=10)
    except:
        pass
    return redirect("/dashboard")


# ══════════════════════════════════════
# LOGOUT
# ══════════════════════════════════════
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=80, debug=True)
