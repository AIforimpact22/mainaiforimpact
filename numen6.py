from flask import Blueprint, render_template

numen6_bp = Blueprint("numen6", __name__, template_folder="templates")


@numen6_bp.get("/")
def numen6_home():
    return render_template("numen6.html")
