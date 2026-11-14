# License: LGPL-3
{
    "name": "Ecuador SRI e-Invoicing (XAdES-BES)",
    "version": "17.0.1.0.0",
    "summary": "Sign, send and authorize Ecuador SRI electronic invoices from Odoo",
    "description": """
Ecuador SRI electronic invoicing for Odoo
=========================================

Turns a posted customer invoice into an SRI *factura*: builds the XML, computes
the 49-digit clave de acceso, signs it with your .p12 (XAdES-BES), sends it to
the SRI recepcion/autorizacion web services and attaches the authorized XML and
a RIDE PDF.

This is a thin Odoo layer over the framework-agnostic ``sri-einvoice`` engine
(Apache-2.0); all of the SRI-specific logic lives in that audited library, not
duplicated here.
    """,
    "author": "Martin Velez",
    "website": "https://github.com/martinvelezf/sri-einvoice",
    "license": "LGPL-3",
    "category": "Accounting/Localizations/EDI",
    "depends": ["account"],
    "external_dependencies": {
        "python": ["lxml", "cryptography", "sri_einvoice"],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/res_config_settings_views.xml",
        "views/account_move_views.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
}
