import logging
import io
import base64
from odoo import models, api

_logger = logging.getLogger(__name__)

try:
    import PyPDF2

    try:
        from PyPDF2.errors import PdfReadError
    except ImportError:
        from PyPDF2 import PdfReadError
except ImportError:
    class PdfReadError(Exception):
        pass


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    def _render_qweb_pdf(self, report_ref, docids, data=None):
        """
        Override the main PDF rendering method
        """
        # Call parent to get the original PDF
        pdf_content, report_type = super()._render_qweb_pdf(report_ref, docids, data=data)

        # Get the report
        report = self._get_report(report_ref)

        # Check if this is a sales order report
        if (report.report_name == 'sale.report_saleorder' and
                report.model == 'sale.order' and
                docids and
                pdf_content):

            try:
                # Get the sale order record
                record = self.env['sale.order'].browse(docids[0])
                if record.exists():
                    # Get product attachments
                    product_attachments = self._get_product_attachments(record)

                    if product_attachments:
                        _logger.info(f"📎 Found {len(product_attachments)} attachments for merging")

                        # Convert PDF content to buffer
                        pdf_buffer = io.BytesIO(pdf_content)

                        # Append attachments at the end
                        merged_buffer = self._append_attachments_to_pdf(pdf_buffer, product_attachments)

                        if merged_buffer:
                            merged_pdf_content = merged_buffer.getvalue()
                            _logger.info("✅ PDF merged successfully - documents at the end")
                            return merged_pdf_content, report_type
                    else:
                        _logger.info("📭 No attachments found to merge")

            except Exception as e:
                _logger.error(f"❌ Error in PDF processing: {str(e)}")

        return pdf_content, report_type

    def _append_attachments_to_pdf(self, original_buffer, attachments):
        """
        Append PDF attachments to the original PDF buffer
        """
        try:
            # Create PDF merger
            merger = PyPDF2.PdfMerger()

            # Add original report PDF
            original_buffer.seek(0)
            merger.append(original_buffer)

            # Append each product attachment
            appended_count = 0
            for attachment in attachments:
                try:
                    if self._append_single_attachment(merger, attachment):
                        appended_count += 1
                        _logger.info(f"✅ Appended: {attachment.name}")
                except Exception as e:
                    _logger.error(f"❌ Error appending {attachment.name}: {str(e)}")
                    continue

            if appended_count > 0:
                # Create new buffer with merged content
                merged_buffer = io.BytesIO()
                merger.write(merged_buffer)
                merger.close()
                merged_buffer.seek(0)

                _logger.info(f"🎉 Successfully merged {appended_count} attachments")
                return merged_buffer
            else:
                merger.close()
                _logger.info("📭 No attachments were successfully appended")
                return None

        except Exception as e:
            _logger.error(f"💥 Error in PDF merging: {str(e)}")
            return None

    def _get_product_attachments(self, record):
        """
        Get all product PDF attachments
        """
        try:
            if hasattr(record, 'order_line') and record.order_line:
                product_ids = record.order_line.mapped('product_id')

                if product_ids:
                    product_template_ids = product_ids.mapped('product_tmpl_id').ids

                    attachments = self.env['ir.attachment'].search([
                        ('res_model', '=', 'product.template'),
                        ('res_id', 'in', product_template_ids),
                        ('mimetype', '=', 'application/pdf'),
                    ])

                    return attachments

            return self.env['ir.attachment']

        except Exception as e:
            _logger.error(f"Error fetching attachments: {str(e)}")
            return self.env['ir.attachment']

    def _append_single_attachment(self, merger, attachment):
        """
        Append a single PDF attachment
        """
        try:
            if not attachment.datas:
                _logger.warning(f"📭 No data in attachment: {attachment.name}")
                return False

            # Get the raw data
            raw_data = attachment.datas

            # Decode base64 data
            if isinstance(raw_data, str):
                pdf_data = base64.b64decode(raw_data)
            elif isinstance(raw_data, bytes):
                try:
                    pdf_data = base64.b64decode(raw_data)
                except:
                    pdf_data = raw_data
            else:
                _logger.warning(f"📭 Invalid data type in attachment: {attachment.name}")
                return False

            # Validate PDF
            if len(pdf_data) < 4 or pdf_data[:4] != b'%PDF':
                _logger.warning(f"📭 Not a valid PDF file: {attachment.name}")
                return False

            # Try to parse with PyPDF2
            pdf_buffer = io.BytesIO(pdf_data)
            try:
                reader = PyPDF2.PdfReader(pdf_buffer)
                if len(reader.pages) == 0:
                    _logger.warning(f"📭 PDF has no pages: {attachment.name}")
                    return False
            except PdfReadError:
                _logger.warning(f"📭 Cannot read PDF (PdfReadError): {attachment.name}")
                return False
            except Exception as e:
                _logger.warning(f"📭 PDF parsing error: {attachment.name} - {str(e)}")
                return False

            # Append to merger
            pdf_buffer.seek(0)
            merger.append(pdf_buffer)
            return True

        except Exception as e:
            _logger.error(f"📭 Error processing attachment {attachment.name}: {str(e)}")
            return False
