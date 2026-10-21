from flask import Flask, jsonify, render_template, request

import engine
import replace
from api import bp as api_bp

app = Flask(__name__)
app.register_blueprint(api_bp)


# One HTML shell; the front end routes between its pages on the client.
@app.route("/", methods=["GET"])
@app.route("/titles", methods=["GET"])
@app.route("/settings", methods=["GET"])
@app.route("/history", methods=["GET"])
def ui_shell():
    return render_template("shell.html", version=engine.APP_VERSION)


@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"error": {"code": "not_found", "message": "No such endpoint."}}), 404
    return render_template("shell.html", version=engine.APP_VERSION), 404


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "version": engine.APP_VERSION})


engine.start_background()
replace.start()
