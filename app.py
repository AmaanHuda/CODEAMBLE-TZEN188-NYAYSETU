from flask import Flask, render_template, request, redirect, url_for
from flask_wtf.csrf import CSRFProtect

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("main.html")


@app.route("/new-issue")
def chat():
    return render_template("new-issue.html")


if __name__ == "__main__":
    app.run(debug=True, port=9000)