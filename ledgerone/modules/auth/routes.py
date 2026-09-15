from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from ledgerone.extensions import db
from ledgerone.models.core import Membership, User

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _safe_next(target: str | None) -> bool:
    if not target:
        return False
    host = urlparse(request.host_url)
    resolved = urlparse(urljoin(request.host_url, target))
    return resolved.scheme in {"http", "https"} and host.netloc == resolved.netloc


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("core.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email, is_active=True).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            membership = (
                Membership.query.filter_by(user_id=user.id, is_active=True)
                .order_by(Membership.created_at.asc())
                .first()
            )
            if membership:
                session["organisation_id"] = membership.organisation_id
            target = request.args.get("next")
            return redirect(target if _safe_next(target) else url_for("core.dashboard"))
        flash("Email or password was not recognised.", "danger")

    return render_template("auth/login.html")


@bp.post("/logout")
@login_required
def logout():
    # Clear application session state first, then let Flask-Login mark the
    # remember-me cookie for deletion. Calling session.clear() after
    # logout_user() would remove Flask-Login's `_remember = "clear"` marker,
    # allowing the persistent cookie to authenticate the user again immediately.
    session.clear()
    logout_user()
    return redirect(url_for("auth.login"))


@bp.post("/ui-mode")
@login_required
def ui_mode():
    mode = request.form.get("mode", "home")
    if mode not in {"home", "professional"}:
        mode = "home"
    current_user.ui_mode = mode
    db.session.commit()
    return redirect(request.referrer or url_for("core.dashboard"))


@bp.post("/organisation")
@login_required
def switch_organisation():
    organisation_id = request.form.get("organisation_id")
    membership = Membership.query.filter_by(
        organisation_id=organisation_id,
        user_id=current_user.id,
        is_active=True,
    ).first_or_404()
    session["organisation_id"] = membership.organisation_id
    return redirect(request.referrer or url_for("core.dashboard"))
