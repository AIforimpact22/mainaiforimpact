# contact.py
from flask import Blueprint, render_template

# Name it "contact" so url_for('contact.contact_page') is intuitive
contact_bp = Blueprint("contact", __name__)

# Accept /contact and /contact/ (strict_slashes=False)
@contact_bp.route("/", methods=["GET"], strict_slashes=False)
def contact_page():
    # We purposely render base.html because your base shows the Contact content
    # when request.path starts with bp('/contact').
    return render_template("base.html")
