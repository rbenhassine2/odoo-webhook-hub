{
    'name': 'Webhook Integration Hub',
    'version': '17.0.1.0.0',
    'category': 'Technical/Integrations',
    'summary': 'Robust inbound webhook receiver with HMAC signature verification, idempotent processing, retries, and audit logs.',
    'description': """
Webhook Integration Hub for Odoo 17 & 18/19
==========================================
Provides an enterprise-ready ingestion pipeline for external webhooks (Salesforce Outbound Messages / Platform Events, Stripe, ChargeOver, Shopify, custom microservices):
* Endpoint with configurable HMAC SHA256 / Bearer token authentication
* Idempotency checking to eliminate duplicate event execution
* Full payload audit logging with execution timing, error stack traces, and request headers
* Asynchronous retry mechanism via scheduled actions (cron) with exponential backoff
* Pluggable payload routing and handler registration
    """,
    'author': 'Raouf Ben Hassine',
    'website': 'https://rbenhassine.com',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/cron.xml',
        'views/webhook_endpoint_views.xml',
        'views/webhook_event_views.xml',
        'views/menus.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
