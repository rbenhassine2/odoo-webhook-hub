import secrets

from odoo import api, fields, models


class WebhookEndpoint(models.Model):
    _name = 'webhook.endpoint'
    _description = 'Inbound Webhook Endpoint Configuration'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(string='Name', required=True, tracking=True)
    code = fields.Char(
        string='Endpoint Identifier / Slug',
        required=True,
        copy=False,
        index=True,
        help="Unique identifier used in URL: /api/v1/webhook/<slug>",
    )
    active = fields.Boolean(default=True, tracking=True)
    description = fields.Text(string='Description')

    # Security / Auth
    auth_type = fields.Selection(
        selection=[
            ('none', 'No Verification (Insecure)'),
            ('bearer', 'Bearer Token / API Key'),
            ('hmac_sha256', 'HMAC-SHA256 Signature'),
        ],
        string='Authentication Method',
        default='hmac_sha256',
        required=True,
        tracking=True,
    )
    secret_key = fields.Char(
        string='Secret / Signing Key',
        copy=False,
        default=lambda self: secrets.token_hex(24),
        help="Shared secret for HMAC verification or expected Bearer token.",
    )
    signature_header = fields.Char(
        string='Signature Header Name',
        default='X-Signature-SHA256',
        help="Header containing the signature (e.g. X-Signature-SHA256, X-Hub-Signature-256, Stripe-Signature).",
    )
    idempotency_header = fields.Char(
        string='Idempotency Key Header',
        default='X-Idempotency-Key',
        help="Optional HTTP header containing a unique idempotency key.",
    )
    idempotency_json_path = fields.Char(
        string='Idempotency JSON Field',
        default='id',
        help="Dot-notation path inside JSON payload for idempotency key if header is absent (e.g. 'event_id' or 'id').",
    )

    # Processing configuration
    target_model_id = fields.Many2one(
        'ir.model',
        string='Target Model for Processing',
        help="Odoo model that implements the handler method to consume this webhook.",
        ondelete='set null',
    )
    handler_method = fields.Char(
        string='Handler Method Name',
        default='process_webhook_event',
        help="Method name on the target model that accepts (event_record). E.g. process_webhook_event",
    )
    process_mode = fields.Selection(
        selection=[
            ('sync', 'Synchronous (Process Immediately)'),
            ('async', 'Asynchronous (Queue for Cron Worker)'),
        ],
        string='Processing Mode',
        default='sync',
        required=True,
        help="Sync executes during the HTTP request. Async queues the event as 'pending' for batch cron execution.",
    )
    max_retries = fields.Integer(string='Max Retry Attempts', default=5)

    # Statistics & Telemetry
    event_count = fields.Integer(string='Total Events', compute='_compute_event_stats')
    failed_count = fields.Integer(string='Failed Events', compute='_compute_event_stats')

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'The endpoint identifier slug must be unique.'),
    ]

    @api.depends()
    def _compute_event_stats(self):
        event_obj = self.env['webhook.event']
        for record in self:
            record.event_count = event_obj.search_count([('endpoint_id', '=', record.id)])
            record.failed_count = event_obj.search_count([('endpoint_id', '=', record.id), ('state', '=', 'failed')])

    def action_generate_secret(self):
        for record in self:
            record.secret_key = secrets.token_hex(24)

    def action_view_events(self):
        self.ensure_one()
        return {
            'name': f'Events: {self.name}',
            'type': 'ir.actions.act_window',
            'res_model': 'webhook.event',
            'view_mode': 'tree,form',
            'domain': [('endpoint_id', '=', self.id)],
            'context': {'default_endpoint_id': self.id},
        }
