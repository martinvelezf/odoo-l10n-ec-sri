# License: LGPL-3
"""Bridge a posted customer invoice to the ``sri-einvoice`` engine.

Nothing SRI-specific is reimplemented here: the module maps an ``account.move``
onto the library's typed ``Factura`` and calls the library to build, sign, send
and authorize. Signing material (the .p12 and its password) is resolved on the
company and never logged.
"""

import base64
import logging
from datetime import date

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

SRI_STATE = [
    ("draft", "Draft"),
    ("signed", "Signed"),
    ("sent", "Sent to SRI"),
    ("authorized", "Authorized"),
    ("rejected", "Rejected"),
    ("returned", "Returned"),
]

# SRI codigo_porcentaje for IVA by rate. Kept minimal and explicit; the heavy
# tax logic lives in the library, this only classifies the Odoo tax amount.
_IVA_CODE_BY_RATE = {
    0.0: "0",
    12.0: "2",
    14.0: "3",
    15.0: "4",
    5.0: "5",
}


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_ec_clave_acceso = fields.Char(
        "Clave de acceso", copy=False, readonly=True, size=49
    )
    l10n_ec_sri_state = fields.Selection(
        SRI_STATE, string="SRI status", default="draft", copy=False, readonly=True
    )
    l10n_ec_sri_authorization = fields.Char(
        "Authorization number", copy=False, readonly=True
    )
    l10n_ec_sri_authorization_date = fields.Char(
        "Authorization date", copy=False, readonly=True,
        help="Authorization timestamp as returned by the SRI.",
    )
    l10n_ec_sri_messages = fields.Text("SRI messages", copy=False, readonly=True)

    # ------------------------------------------------------------------
    # mapping helpers
    # ------------------------------------------------------------------
    def _l10n_ec_build_factura(self):
        """Map this invoice onto a library ``Factura``. Pure, no I/O."""
        self.ensure_one()
        try:
            from sri_einvoice import (
                Comprador,
                Detalle,
                Emisor,
                Factura,
                Impuesto,
            )
        except ImportError as exc:  # pragma: no cover - env guard
            raise UserError(
                _("The 'sri-einvoice' Python package is not installed on the server.")
            ) from exc

        company = self.company_id
        partner = self.partner_id
        if not company.vat:
            raise UserError(_("The company has no RUC set."))

        emisor = Emisor(
            ruc=company.vat,
            razon_social=company.name,
            dir_matriz=company.street or "",
            nombre_comercial=company.name,
            obligado_contabilidad="SI"
            if company.l10n_ec_sri_obligado_contabilidad
            else "NO",
        )

        ident = partner.vat or "9999999999999"
        tipo_ident = "04" if len(ident) == 13 else "05"
        comprador = Comprador(
            tipo_identificacion=tipo_ident,
            identificacion=ident,
            razon_social=partner.name or "CONSUMIDOR FINAL",
            direccion=partner.street or None,
            email=partner.email or None,
        )

        detalles = []
        for line in self.invoice_line_ids.filtered(
            lambda l: l.display_type in (False, "product")
        ):
            rate = max((t.amount for t in line.tax_ids), default=0.0)
            iva_code = _IVA_CODE_BY_RATE.get(rate, "4")
            detalles.append(
                Detalle(
                    descripcion=line.name or (line.product_id.display_name or "-"),
                    cantidad=line.quantity,
                    precio_unitario=line.price_unit,
                    codigo_principal=line.product_id.default_code or None,
                    descuento=line.price_unit * line.quantity
                    * (line.discount or 0.0) / 100.0,
                    iva_codigo_porcentaje=iva_code,
                )
            )
        if not detalles:
            raise UserError(_("The invoice has no billable lines."))

        emission = self.invoice_date or date.today()
        factura = Factura(
            emisor=emisor,
            comprador=comprador,
            fecha_emision=emission,
            estab=company.l10n_ec_sri_estab or "001",
            pto_emi=company.l10n_ec_sri_pto_emi or "001",
            secuencial=(self.name or "").split("/")[-1].zfill(9)[-9:] or "000000001",
            detalles=detalles,
            ambiente="2" if company.l10n_ec_sri_ambiente == "produccion" else "1",
        )
        return factura

    def _l10n_ec_build_nota_credito(self):
        """Map this credit note (out_refund) onto a library ``NotaCredito``."""
        self.ensure_one()
        try:
            from sri_einvoice import Comprador, Detalle, Emisor, NotaCredito
        except ImportError as exc:  # pragma: no cover - env guard
            raise UserError(
                _("The 'sri-einvoice' Python package is not installed on the server.")
            ) from exc

        company = self.company_id
        partner = self.partner_id
        if not company.vat:
            raise UserError(_("The company has no RUC set."))

        origin = self.reversed_entry_id
        if not origin:
            raise UserError(
                _("A credit note must reference the invoice it modifies "
                  "(set 'Reversal of' / reversed_entry_id).")
            )
        orig_sec = (origin.name or "").split("/")[-1].zfill(9)[-9:]
        estab = company.l10n_ec_sri_estab or "001"
        pto_emi = company.l10n_ec_sri_pto_emi or "001"
        num_doc_modificado = f"{estab}-{pto_emi}-{orig_sec}"

        emisor = Emisor(
            ruc=company.vat,
            razon_social=company.name,
            dir_matriz=company.street or "",
            nombre_comercial=company.name,
            dir_establecimiento=company.street or None,
            obligado_contabilidad="SI"
            if company.l10n_ec_sri_obligado_contabilidad
            else "NO",
        )
        ident = partner.vat or "9999999999999"
        tipo_ident = "04" if len(ident) == 13 else "05"
        comprador = Comprador(
            tipo_identificacion=tipo_ident,
            identificacion=ident,
            razon_social=partner.name or "CONSUMIDOR FINAL",
            direccion=partner.street or None,
            email=partner.email or None,
        )

        detalles = []
        for line in self.invoice_line_ids.filtered(
            lambda l: l.display_type in (False, "product")
        ):
            rate = max((t.amount for t in line.tax_ids), default=0.0)
            iva_code = _IVA_CODE_BY_RATE.get(rate, "4")
            detalles.append(
                Detalle(
                    descripcion=line.name or (line.product_id.display_name or "-"),
                    cantidad=line.quantity,
                    precio_unitario=line.price_unit,
                    codigo_principal=line.product_id.default_code or None,
                    descuento=line.price_unit * line.quantity
                    * (line.discount or 0.0) / 100.0,
                    iva_codigo_porcentaje=iva_code,
                )
            )
        if not detalles:
            raise UserError(_("The credit note has no billable lines."))

        return NotaCredito(
            emisor=emisor,
            comprador=comprador,
            fecha_emision=self.invoice_date or date.today(),
            estab=estab,
            pto_emi=pto_emi,
            secuencial=(self.name or "").split("/")[-1].zfill(9)[-9:] or "000000001",
            detalles=detalles,
            cod_doc_modificado="01",
            num_doc_modificado=num_doc_modificado,
            fecha_emision_doc_sustento=origin.invoice_date or self.invoice_date or date.today(),
            motivo=self.ref or _("Nota de credito"),
            ambiente="2" if company.l10n_ec_sri_ambiente == "produccion" else "1",
        )

    def _l10n_ec_signing_identity(self):
        self.ensure_one()
        company = self.company_id
        if not company.l10n_ec_sri_p12:
            raise UserError(_("No signing certificate (.p12) configured for the company."))
        from sri_einvoice.xades import SigningIdentity

        data = base64.b64decode(company.l10n_ec_sri_p12)
        password = company._l10n_ec_sri_password()
        if not password:
            raise UserError(
                _("No certificate password set (SRI_P12_PASSWORD env or company field).")
            )
        return SigningIdentity.from_p12(data, password)

    def _l10n_ec_attach(self, name, raw_bytes):
        return self.env["ir.attachment"].create(
            {
                "name": name,
                "res_model": "account.move",
                "res_id": self.id,
                "raw": raw_bytes,
            }
        )

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def action_sri_build_sign(self):
        from sri_einvoice.xades import sign_xml
        from sri_einvoice.xmlbuild import (
            build_factura_xml,
            build_nota_credito_xml,
            to_bytes,
        )

        for move in self:
            if move.move_type not in ("out_invoice", "out_refund"):
                raise UserError(_("Only customer invoices can be issued to the SRI."))
            if move.move_type == "out_refund":
                comprobante = move._l10n_ec_build_nota_credito()
                root = build_nota_credito_xml(comprobante)
            else:
                comprobante = move._l10n_ec_build_factura()
                root = build_factura_xml(comprobante)
            identity = move._l10n_ec_signing_identity()
            signed = sign_xml(
                to_bytes(root), identity, algorithm=move.company_id.l10n_ec_sri_algorithm
            )
            move.l10n_ec_clave_acceso = comprobante.clave_acceso
            move._l10n_ec_attach(f"{comprobante.clave_acceso}.xml", signed)
            move.l10n_ec_sri_state = "signed"
        return True

    def action_sri_send(self):
        from sri_einvoice.soap import SriClient

        for move in self:
            if move.l10n_ec_sri_state not in ("signed", "returned"):
                raise UserError(_("Sign the invoice before sending it to the SRI."))
            signed = move._l10n_ec_latest_signed_xml()
            ambiente = (
                "produccion"
                if move.company_id.l10n_ec_sri_ambiente == "produccion"
                else "pruebas"
            )
            client = SriClient(ambiente=ambiente)
            resp = client.enviar(signed)
            estado = getattr(resp, "estado", "")
            move.l10n_ec_sri_messages = str(getattr(resp, "mensajes", "") or estado)
            move.l10n_ec_sri_state = "sent" if estado == "RECIBIDA" else "rejected"
        return True

    def action_sri_authorize(self):
        from sri_einvoice.soap import SriClient, autorizacion_to_xml
        from sri_einvoice.ride import render_ride

        for move in self:
            if not move.l10n_ec_clave_acceso:
                raise UserError(_("No clave de acceso; sign and send first."))
            ambiente = (
                "produccion"
                if move.company_id.l10n_ec_sri_ambiente == "produccion"
                else "pruebas"
            )
            client = SriClient(ambiente=ambiente)
            respuesta = client.esperar_autorizacion(move.l10n_ec_clave_acceso)
            aut = respuesta.autorizado  # first AUTORIZADO Autorizacion, or None
            if aut is None:
                move.l10n_ec_sri_messages = (
                    "; ".join(
                        str(a.mensajes or a.estado) for a in respuesta.autorizaciones
                    )
                    or "EN PROCESO"
                )
                move.l10n_ec_sri_state = "rejected"
                continue
            move.l10n_ec_sri_messages = str(aut.mensajes or aut.estado)
            authorized_xml = autorizacion_to_xml(aut)
            move.l10n_ec_sri_authorization = (
                aut.numero_autorizacion or move.l10n_ec_clave_acceso
            )
            move.l10n_ec_sri_authorization_date = aut.fecha_autorizacion or ""
            att = move._l10n_ec_attach(
                f"{move.l10n_ec_clave_acceso}_aut.xml", authorized_xml
            )
            # RIDE PDF alongside the authorized XML
            import tempfile
            import os

            with tempfile.TemporaryDirectory() as tmp:
                pdf_path = os.path.join(tmp, f"{move.l10n_ec_clave_acceso}.pdf")
                render_ride(authorized_xml, pdf_path)
                with open(pdf_path, "rb") as fh:
                    move._l10n_ec_attach(
                        f"{move.l10n_ec_clave_acceso}.pdf", fh.read()
                    )
            move.l10n_ec_sri_state = "authorized"
            _logger.info("SRI authorized %s (attachment %s)", move.name, att.id)
        return True

    def _l10n_ec_latest_signed_xml(self):
        self.ensure_one()
        att = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "account.move"),
                ("res_id", "=", self.id),
                ("name", "=", f"{self.l10n_ec_clave_acceso}.xml"),
            ],
            limit=1,
        )
        if not att:
            raise UserError(_("Signed XML attachment not found; sign again."))
        return base64.b64decode(att.datas)
