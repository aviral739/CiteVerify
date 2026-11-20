"""
Regression and unit tests for CORS configuration and origin parsing.
Validates:
1. Parsing of JSON strings, comma-separated lists, and list literals in CORS_ORIGINS
2. Stripping of trailing slashes from configured origins
3. Correct CORS preflight headers for production Netlify origin
4. Correct CORS preflight headers for local development origins
5. Proper rejection of disallowed / untrusted origins with 400 Bad Request
6. Verification that Starlette CORSMiddleware correctly recognizes configured origins
"""

import sys
from pathlib import Path
import pytest

# Ensure root directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def setup_test_database():
    """Bypass conftest database initialization for pure CORS unit tests."""
    yield


def get_configured_cors_middleware():
    """Build the exact CORSMiddleware instance used by CiteVerify."""
    settings = get_settings()
    origins = [str(o).strip().rstrip("/") for o in settings.CORS_ORIGINS]
    return CORSMiddleware(
        app=None,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        allow_headers=["*"],
        expose_headers=["Content-Type", "Content-Disposition", "Content-Length", "X-Request-ID"],
        max_age=600,
    )


def test_cors_origins_parsing():
    """Verify that Settings.assemble_cors_origins parses diverse environment formats and strips trailing slashes."""
    # Test JSON string parsing
    settings_json = Settings(
        CORS_ORIGINS='["http://localhost:5173", "https://sweet-gumdrop-378fba.netlify.app/"]'
    )
    assert "http://localhost:5173" in settings_json.CORS_ORIGINS
    assert "https://sweet-gumdrop-378fba.netlify.app" in settings_json.CORS_ORIGINS
    assert "https://sweet-gumdrop-378fba.netlify.app/" not in settings_json.CORS_ORIGINS

    # Test comma-separated string parsing
    settings_comma = Settings(
        CORS_ORIGINS="http://localhost:3000, https://sweet-gumdrop-378fba.netlify.app/"
    )
    assert "http://localhost:3000" in settings_comma.CORS_ORIGINS
    assert "https://sweet-gumdrop-378fba.netlify.app" in settings_comma.CORS_ORIGINS

    # Test list format
    settings_list = Settings(
        CORS_ORIGINS=["http://localhost:5173/", "https://sweet-gumdrop-378fba.netlify.app"]
    )
    assert "http://localhost:5173" in settings_list.CORS_ORIGINS
    assert "https://sweet-gumdrop-378fba.netlify.app" in settings_list.CORS_ORIGINS


def test_cors_preflight_netlify_origin():
    """Test preflight OPTIONS request from the production Netlify origin succeeds with 200 and required CORS headers."""
    cors = get_configured_cors_middleware()
    origin = "https://sweet-gumdrop-378fba.netlify.app"
    req_headers = Headers({
        "origin": origin,
        "access-control-request-method": "POST",
        "access-control-request-headers": "content-type",
    })

    resp = cors.preflight_response(request_headers=req_headers)
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin
    assert resp.headers.get("access-control-allow-credentials") == "true"
    assert "POST" in resp.headers.get("access-control-allow-methods", "")
    assert resp.headers.get("access-control-max-age") == "600"
    assert "Content-Type" in cors.simple_headers.get("Access-Control-Expose-Headers", "")


def test_cors_preflight_localhost_origin():
    """Test preflight OPTIONS request from local development origin succeeds with 200."""
    cors = get_configured_cors_middleware()
    origin = "http://localhost:5173"
    req_headers = Headers({
        "origin": origin,
        "access-control-request-method": "POST",
        "access-control-request-headers": "content-type",
    })

    resp = cors.preflight_response(request_headers=req_headers)
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin
    assert resp.headers.get("access-control-allow-credentials") == "true"


def test_cors_disallowed_origin_rejected():
    """Test preflight OPTIONS request from an untrusted origin is rejected with 400 Disallowed CORS origin."""
    cors = get_configured_cors_middleware()
    origin = "https://malicious-unauthorized-site.com"
    req_headers = Headers({
        "origin": origin,
        "access-control-request-method": "POST",
        "access-control-request-headers": "content-type",
    })

    resp = cors.preflight_response(request_headers=req_headers)
    assert resp.status_code == 400
    assert b"Disallowed CORS origin" in resp.body
    assert resp.headers.get("access-control-allow-origin") is None


def test_cors_is_allowed_origin():
    """Verify is_allowed_origin accurately identifies permitted vs forbidden origins."""
    cors = get_configured_cors_middleware()
    assert cors.is_allowed_origin("https://sweet-gumdrop-378fba.netlify.app") is True
    assert cors.is_allowed_origin("http://localhost:5173") is True
    assert cors.is_allowed_origin("http://127.0.0.1:8000") is False
    assert cors.is_allowed_origin("https://arbitrary-attacker.com") is False


if __name__ == "__main__":
    test_cors_origins_parsing()
    test_cors_preflight_netlify_origin()
    test_cors_preflight_localhost_origin()
    test_cors_disallowed_origin_rejected()
    test_cors_is_allowed_origin()
    print("ALL 5 CORS REGRESSION TESTS PASSED SUCCESSFULLY!")
