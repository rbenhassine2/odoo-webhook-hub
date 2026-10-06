import hashlib
import hmac
import json
import logging
import time

from odoo import http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class WebhookReceiverController(http.Controller):
    @http.route(
        '/api/v1/webhook/<string:endpoint_slug>',
        type='http',
        auth='none',
        methods=['POST'],
        csrf=False,
    )
    def receive_webhook(self, endpoint_slug, **kwargs):
        """Unified ingestion route for inbound webhooks."""
        start_time = time.time()
        raw_body = request.httprequest.data or b''
        headers = dict(request.httprequest.headers)
        client_ip = request.httprequest.remote_addr

        # Locate Endpoint configuration using sudo() since auth='none'
        endpoint = (
            request.env['webhook.endpoint']
            .sudo()
            .search([('code', '=', endpoint_slug), ('active', '=', True)], limit=1)
        )

        if not endpoint:
            _logger.warning("Webhook received for unknown or disabled endpoint slug: %s", endpoint_slug)
            return self._json_response({'error': 'Endpoint not found or inactive'}, status=404)

        # 1. Security / Authentication Verification
        is_authenticated, auth_error = self._verify_authentication(endpoint, headers, raw_body)
        if not is_authenticated:
            _logger.warning("Authentication failed for webhook %s: %s", endpoint_slug, auth_error)
            return self._json_response({'error': auth_error}, status=401)

        # 2. Extract Idempotency Key
        idempotency_key = self._extract_idempotency_key(endpoint, headers, raw_body)

        # 3. Check for existing event with identical idempotency key
        event_obj = request.env['webhook.event'].sudo()
        if idempotency_key:
            existing_event = event_obj.search(
                [('endpoint_id', '=', endpoint.id), ('idempotency_key', '=', idempotency_key)],
                limit=1,
            )

            if existing_event:
                _logger.info(
                    "Duplicate webhook detected for endpoint %s with key %s (existing state: %s)",
                    endpoint_slug,
                    idempotency_key,
                    existing_event.state,
                )
                return self._json_response(
                    {
                        'status': 'duplicate_ignored',
                        'event_id': existing_event.id,
                        'message': 'Event already received and processed or queued.',
                    },
                    status=200,
                )

        # 4. Create Audit Log / Event Record
        try:
            event = event_obj.create(
                {
                    'endpoint_id': endpoint.id,
                    'idempotency_key': idempotency_key,
                    'http_method': request.httprequest.method,
                    'remote_ip': client_ip,
                    'headers_json': json.dumps(headers, default=str),
                    'payload_raw': raw_body.decode('utf-8', errors='replace'),
                    'state': 'pending',
                },
            )
        except Exception:
            _logger.exception("Failed to persist webhook event record")
            return self._json_response({'error': 'Internal server error recording event'}, status=500)

        # 5. Execution based on process_mode (sync vs async)
        if endpoint.process_mode == 'sync':
            success = event.process_event()
            event.write({'response_code': 200 if success else 500})
            if success:
                return self._json_response(
                    {
                        'status': 'success',
                        'event_id': event.id,
                        'execution_time_ms': round((time.time() - start_time) * 1000, 2),
                    },
                    status=200,
                )
            return self._json_response(
                {
                    'status': 'failed_queued_for_retry',
                    'event_id': event.id,
                    'error': event.error_message,
                },
                status=500,
            )
        # Asynchronous mode: acknowledge receipt immediately, processed by cron
        event.write({'response_code': 202})
        return self._json_response(
            {
                'status': 'accepted',
                'event_id': event.id,
                'message': 'Event successfully accepted and queued for background processing.',
            },
            status=202,
        )

    def _verify_authentication(self, endpoint, headers, raw_body):
        """Validates Bearer token or HMAC SHA256 signature."""
        if endpoint.auth_type == 'none':
            return True, None

        if endpoint.auth_type == 'bearer':
            auth_header = headers.get('Authorization', '')
            expected = f"Bearer {endpoint.secret_key}"
            if not auth_header or auth_header.strip() != expected.strip():
                return False, 'Invalid or missing Bearer token'
            return True, None

        if endpoint.auth_type == 'hmac_sha256':
            header_name = endpoint.signature_header or 'X-Signature-SHA256'
            signature = headers.get(header_name)
            if not signature:
                return False, f"Missing signature header '{header_name}'"

            # Clean prefix if format is sha256=... (e.g., GitHub, Stripe, Shopify format)
            if '=' in signature:
                parts = signature.split('=', 1)
                signature = parts[1].strip()

            secret_bytes = (endpoint.secret_key or '').encode('utf-8')
            computed_hmac = hmac.new(secret_bytes, raw_body, hashlib.sha256).hexdigest()

            # Constant-time comparison against timing attacks
            if not hmac.compare_digest(computed_hmac, signature):
                return False, "Signature verification failed (HMAC mismatch)"

            return True, None

        return False, "Unsupported authentication type"

    def _extract_idempotency_key(self, endpoint, headers, raw_body):
        """Extracts idempotency key from designated header or parsed JSON payload."""
        # Check Header first
        if endpoint.idempotency_header:
            header_val = headers.get(endpoint.idempotency_header)
            if header_val:
                return header_val.strip()

        # Check JSON path if body is present
        if endpoint.idempotency_json_path and raw_body:
            try:
                data = json.loads(raw_body.decode('utf-8'))
            except (ValueError, UnicodeDecodeError):
                return None

            keys = endpoint.idempotency_json_path.split('.')
            val = data
            for k in keys:
                if isinstance(val, dict) and k in val:
                    val = val[k]
                else:
                    val = None
                    break
            if val is not None:
                return str(val)

        return None

    def _json_response(self, data, status=200):
        return Response(json.dumps(data), status=status, headers={'Content-Type': 'application/json'})
