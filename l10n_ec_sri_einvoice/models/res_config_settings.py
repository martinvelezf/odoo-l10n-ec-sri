# License: LGPL-3
"""SRI issuer configuration, held on the company.

The .p12 is stored on the company as a binary field. Its password is read from
the ``SRI_P12_PASSWORD`` environment variable first (so the secret need never
live in the database); a stored fallback field exists for single-tenant setups
but is marked as sensitive in the UI.
"""

import os

from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    l10n_ec_sri_ambiente = fields.Selection(
        [("pruebas", "Pruebas (test)"), ("produccion", "Producción")],
        string="SRI environment",
        default="pruebas",
    )
    l10n_ec_sri_estab = fields.Char("Establecimiento", size=3, default="001")
    l10n_ec_sri_pto_emi = fields.Char("Punto de emisión", size=3, default="001")
    l10n_ec_sri_obligado_contabilidad = fields.Boolean(
        "Obligado a llevar contabilidad", default=True
    )
    l10n_ec_sri_p12 = fields.Binary("Signing certificate (.p12)", attachment=True)
    l10n_ec_sri_p12_filename = fields.Char("Certificate filename")
    l10n_ec_sri_p12_password = fields.Char(
        "Certificate password",
        help="Stored in the database. Prefer the SRI_P12_PASSWORD environment "
        "variable, which takes precedence over this field.",
    )
    l10n_ec_sri_algorithm = fields.Selection(
        [("sha1", "RSA-SHA1 (SRI profile)"), ("sha256", "RSA-SHA256")],
        string="Signature algorithm",
        default="sha1",
    )

    def _l10n_ec_sri_password(self):
        """Resolve the .p12 password: environment variable wins."""
        self.ensure_one()
        return os.environ.get("SRI_P12_PASSWORD") or self.l10n_ec_sri_p12_password or ""


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    l10n_ec_sri_ambiente = fields.Selection(
        related="company_id.l10n_ec_sri_ambiente", readonly=False
    )
    l10n_ec_sri_estab = fields.Char(
        related="company_id.l10n_ec_sri_estab", readonly=False
    )
    l10n_ec_sri_pto_emi = fields.Char(
        related="company_id.l10n_ec_sri_pto_emi", readonly=False
    )
    l10n_ec_sri_obligado_contabilidad = fields.Boolean(
        related="company_id.l10n_ec_sri_obligado_contabilidad", readonly=False
    )
    l10n_ec_sri_p12 = fields.Binary(
        related="company_id.l10n_ec_sri_p12", readonly=False
    )
    l10n_ec_sri_p12_filename = fields.Char(
        related="company_id.l10n_ec_sri_p12_filename", readonly=False
    )
    l10n_ec_sri_p12_password = fields.Char(
        related="company_id.l10n_ec_sri_p12_password", readonly=False
    )
    l10n_ec_sri_algorithm = fields.Selection(
        related="company_id.l10n_ec_sri_algorithm", readonly=False
    )
