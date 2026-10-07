{
    'name': 'Webhook Integration Hub',
    'version': '17.0.1.0.0',
    'category': 'Technical/Integrations',
    'summary': 'Inbound webhook receiver with audit logs and retries',
    'author': 'Raouf Ben Hassine',
    'website': 'https://rbenhassine.com',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/webhook_endpoint_views.xml',
        'views/webhook_event_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
}
