import logging

from flask import Flask, jsonify

from . import auth, db
from .api import BLUEPRINTS
from .validators import ValidationError


def create_app(overrides=None):
    app = Flask(__name__)
    app.config.from_object("billing.config")
    if overrides:
        app.config.update(overrides)
    logging.basicConfig(level=app.config["LOG_LEVEL"])

    app.teardown_appcontext(db.close)
    app.register_blueprint(auth.bp)
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ValidationError)
    def invalid(error):
        return jsonify(error=str(error), field=error.field), 400

    @app.errorhandler(401)
    def unauthorized(_error):
        return jsonify(error="sign in required"), 401

    @app.errorhandler(403)
    def forbidden(_error):
        return jsonify(error="not allowed"), 403

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error="not found"), 404

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
