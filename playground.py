from flask import Blueprint, render_template

# Blueprint for /play
playground_bp = Blueprint("playground", __name__)

@playground_bp.get("/")
def playground_home():
    # Landing page with two choices
    return render_template("playground.html")
