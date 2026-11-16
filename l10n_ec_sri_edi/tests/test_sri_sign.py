# License: LGPL-3
"""Offline issue flow: posted invoice / credit note -> SRI XML -> XAdES-BES.

Uses a self-signed TEST certificate from the library. Nothing is sent to the
SRI: only action_sri_build_sign (no network) is exercised. If SRI_XSD_DIR points
at the downloaded SRI XSDs the signed XML is also schema-validated.
"""

import base64
import os
from unittest.mock import patch

from lxml import etree

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon

RUC_EMISOR = "1790012345001"
RUC_CLIENTE = "0990000000001"
P12_PASSWORD = "test-only"


@tagged("post_install", "-at_install")
class TestSriSign(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from sri_einvoice.testcert import make_test_p12

        cls.company = cls.company_data["company"]
        cls.company.write(
            {
                "vat": RUC_EMISOR,
                "street": "Av. Amazonas N1-1",
                "l10n_ec_sri_ambiente": "pruebas",
                "l10n_ec_sri_p12": base64.b64encode(
                    make_test_p12(P12_PASSWORD.encode())
                ),
                "l10n_ec_sri_p12_password": P12_PASSWORD,
            }
        )
        cls.partner_a.write({"vat": RUC_CLIENTE, "email": "cliente@example.com"})

    def _signed_xml(self, move):
        att = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "account.move"),
                ("res_id", "=", move.id),
                ("name", "=", "%s.xml" % move.l10n_ec_clave_acceso),
            ]
        )
        self.assertEqual(len(att), 1)
        return base64.b64decode(att.datas)

    def _check_signed(self, move, cod_doc, tag):
        from sri_einvoice.xades import verify_xml

        self.assertEqual(move.l10n_ec_sri_state, "signed")
        clave = move.l10n_ec_clave_acceso
        self.assertEqual(len(clave), 49)
        self.assertEqual(clave[8:10], cod_doc)
        self.assertEqual(clave[10:23], RUC_EMISOR)
        self.assertEqual(clave[23], "1")  # pruebas, never produccion
        xml = self._signed_xml(move)
        result = verify_xml(xml)
        self.assertTrue(result.valid, result.errors)
        root = etree.fromstring(xml)
        self.assertEqual(root.tag, tag)
        xsd_dir = os.environ.get("SRI_XSD_DIR")
        if xsd_dir and os.path.isdir(xsd_dir):
            from sri_einvoice.validate import validate_xml

            self.assertEqual(validate_xml(root, xsd_dir), [])
        return root

    def test_invoice_build_sign(self):
        invoice = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[100.0, 50.0], post=True
        )
        invoice.action_sri_build_sign()
        root = self._check_signed(invoice, "01", "factura")
        self.assertEqual(root.findtext(".//identificacionComprador"), RUC_CLIENTE)
        self.assertEqual(len(root.findall(".//detalle")), 2)

    def test_credit_note_build_sign(self):
        invoice = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[100.0], post=True
        )
        invoice.action_sri_build_sign()
        wizard = (
            self.env["account.move.reversal"]
            .with_context(active_model="account.move", active_ids=invoice.ids)
            .create({"reason": "Devolucion", "journal_id": invoice.journal_id.id})
        )
        refund = self.env["account.move"].browse(wizard.refund_moves()["res_id"])
        self.assertEqual(refund.reversed_entry_id, invoice)
        refund.action_post()
        refund.action_sri_build_sign()
        root = self._check_signed(refund, "04", "notaCredito")
        self.assertEqual(root.findtext(".//codDocModificado"), "01")

    def test_vendor_bill_refused(self):
        bill = self.init_invoice("in_invoice", amounts=[10.0], post=True)
        with self.assertRaises(UserError):
            bill.action_sri_build_sign()

    def test_send_authorize_offline(self):
        """send + authorize + RIDE with a fake SriClient: no network, no SRI."""
        from sri_einvoice import soap

        invoice = self.init_invoice(
            "out_invoice", partner=self.partner_a, amounts=[100.0], post=True
        )
        invoice.action_sri_build_sign()
        signed = self._signed_xml(invoice).decode()
        clave = invoice.l10n_ec_clave_acceso
        sent = []

        class FakeClient:
            def __init__(self, ambiente):
                assert ambiente == "pruebas"

            def enviar(self, xml):
                sent.append(xml)
                return soap.RespuestaRecepcion(estado="RECIBIDA")

            def esperar_autorizacion(self, clave_acceso):
                aut = soap.Autorizacion(
                    estado="AUTORIZADO",
                    numero_autorizacion=clave_acceso,
                    fecha_autorizacion="2026-11-16T10:00:00-05:00",
                    ambiente="PRUEBAS",
                    comprobante=signed,
                )
                return soap.RespuestaAutorizacion(clave_acceso, 1, [aut])

        with patch.object(soap, "SriClient", FakeClient):
            invoice.action_sri_send()
            self.assertEqual(invoice.l10n_ec_sri_state, "sent")
            self.assertEqual(sent[0].decode(), signed)
            invoice.action_sri_authorize()
        self.assertEqual(invoice.l10n_ec_sri_state, "authorized")
        self.assertEqual(invoice.l10n_ec_sri_authorization, clave)
        names = self.env["ir.attachment"].search(
            [("res_model", "=", "account.move"), ("res_id", "=", invoice.id)]
        ).mapped("name")
        self.assertIn("%s_aut.xml" % clave, names)
        self.assertIn("%s.pdf" % clave, names)
