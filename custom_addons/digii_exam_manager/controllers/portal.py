# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal


class CertificatePortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'certificate_count' in counters:
            partner = request.env.user.partner_id
            values['certificate_count'] = request.env['exam.certificate'].sudo().search_count([
                ('partner_id', '=', partner.id),
                ('state', '=', 'approved'),
            ])
        if 'exam_count' in counters:
            values['exam_count'] = request.env['survey.survey'].sudo().search_count([
                ('is_exam', '=', True),
            ])
        return values

    @http.route(
        ['/my/certificates', '/my/certificates/page/<int:page>'],
        type='http', auth='user', website=True,
    )
    def portal_my_certificates(self, page=1, search=None, exam_id=None, **kw):
        partner = request.env.user.partner_id
        Certificate = request.env['exam.certificate'].sudo()
        STEP = 6  # 6 certificats par page

        domain = [
            ('partner_id', '=', partner.id),
            ('state', '=', 'approved'),
        ]

        # Filtre par examen précis (dropdown)
        if exam_id:
            try:
                domain.append(('survey_id', '=', int(exam_id)))
            except (ValueError, TypeError):
                exam_id = None

        # Recherche texte : nom de l'examen OU numéro de certificat
        search = (search or '').strip()
        if search:
            domain += [
                '|',
                ('survey_id.title', 'ilike', search),
                ('name', 'ilike', search),
            ]

        certificate_count = Certificate.search_count(domain)

        # Liste des examens certifiés par ce candidat (pour le menu déroulant)
        all_certs = Certificate.search([
            ('partner_id', '=', partner.id),
            ('state', '=', 'approved'),
        ])
        exam_options = all_certs.mapped('survey_id')

        # Arguments conservés dans la pagination
        url_args = {}
        if search:
            url_args['search'] = search
        if exam_id:
            url_args['exam_id'] = exam_id

        pager = request.website.pager(
            url='/my/certificates',
            url_args=url_args,
            total=certificate_count,
            page=page,
            step=STEP,
        ) if hasattr(request, 'website') and request.website else None

        certificates = Certificate.search(
            domain,
            order='date_approved desc',
            limit=STEP,
            offset=(page - 1) * STEP,
        )

        values = {
            'certificates': certificates,
            'certificate_count': certificate_count,
            'pager': pager,
            'page_name': 'certificates',
            'default_url': '/my/certificates',
            'search': search,
            'exam_id': int(exam_id) if exam_id else False,
            'exam_options': exam_options,
        }
        return request.render(
            'digii_exam_manager.portal_my_certificates', values
        )

    @http.route(
        '/my/certificate/<int:certificate_id>',
        type='http', auth='user', website=True,
    )
    def portal_certificate_detail(self, certificate_id, **kw):
        partner = request.env.user.partner_id
        certificate = request.env['exam.certificate'].sudo().search([
            ('id', '=', certificate_id),
            ('partner_id', '=', partner.id),
            ('state', '=', 'approved'),
        ], limit=1)

        if not certificate:
            return request.redirect('/my/certificates')

        values = {
            'certificate': certificate,
            'page_name': 'certificate_detail',
        }
        return request.render(
            'digii_exam_manager.portal_certificate_detail', values
        )

    @http.route(
        '/exam/certificate/<int:certificate_id>/admin-preview',
        type='http', auth='user', website=True,
    )
    def admin_certificate_preview(self, certificate_id, **kw):
        """Aperçu HTML du certificat pour le back-office (procteur/manager),
        quel que soit l'état (brouillon, en attente, approuvé). Ne dépend pas
        de wkhtmltopdf et évite l'assistant 'Configure document layout'."""
        user = request.env.user
        if not (user.has_group('survey.group_survey_user')
                or user.has_group('base.group_system')):
            return request.redirect('/web')

        certificate = request.env['exam.certificate'].sudo().browse(certificate_id)
        if not certificate.exists():
            return request.redirect('/web')

        Report = request.env['ir.actions.report'].sudo()
        html = Report._render_qweb_html(
            'digii_exam_manager.action_report_exam_certificate',
            [certificate.id],
            data={'screen_preview': True},
        )[0]
        if isinstance(html, bytes):
            html = html.decode('utf-8', errors='replace')
        return request.make_response(
            html, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @http.route(
        '/my/certificate/<int:certificate_id>/preview',
        type='http', auth='user', website=True,
    )
    def portal_certificate_preview(self, certificate_id, **kw):
        """Affiche le PDF du certificat EN LIGNE (inline) pour l'aperçu
        intégré dans la page de détail (iframe). Ne télécharge pas."""
        partner = request.env.user.partner_id
        certificate = request.env['exam.certificate'].sudo().search([
            ('id', '=', certificate_id),
            ('partner_id', '=', partner.id),
            ('state', '=', 'approved'),
        ], limit=1)

        if not certificate:
            return request.redirect('/my/certificates')

        Report = request.env['ir.actions.report'].sudo()
        try:
            pdf_content, _ = Report._render_qweb_pdf(
                'digii_exam_manager.action_report_exam_certificate',
                res_ids=[certificate.id],
            )
            return request.make_response(pdf_content, headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition',
                 f'inline; filename=Certificat_{certificate.name}.pdf'),
                ('Content-Length', len(pdf_content)),
            ])
        except Exception:
            # Repli HTML imprimable si wkhtmltopdf absent
            html = Report._render_qweb_html(
                'digii_exam_manager.action_report_exam_certificate',
                [certificate.id],
                data={'screen_preview': True},
            )[0]
            if isinstance(html, bytes):
                html = html.decode('utf-8', errors='replace')
            return request.make_response(
                html, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @http.route(
        '/my/certificate/<int:certificate_id>/download',
        type='http', auth='user', website=True,
    )
    def portal_certificate_download(self, certificate_id, **kw):
        """Télécharge le PDF du certificat (uniquement si approved)."""
        partner = request.env.user.partner_id
        certificate = request.env['exam.certificate'].sudo().search([
            ('id', '=', certificate_id),
            ('partner_id', '=', partner.id),
            ('state', '=', 'approved'),
        ], limit=1)

        if not certificate:
            return request.redirect('/my/certificates')

        Report = request.env['ir.actions.report'].sudo()
        try:
            pdf_content, _ = Report._render_qweb_pdf(
                'digii_exam_manager.action_report_exam_certificate',
                res_ids=[certificate.id],
            )
            headers = [
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition',
                 f'attachment; filename=Certificat_{certificate.name}.pdf'),
                ('Content-Length', len(pdf_content)),
            ]
            return request.make_response(pdf_content, headers=headers)
        except Exception:
            # wkhtmltopdf absent ou erreur PDF -> repli : certificat en HTML
            # imprimable (l'utilisateur peut faire Ctrl+P -> Enregistrer en PDF).
            html = Report._render_qweb_html(
                'digii_exam_manager.action_report_exam_certificate',
                [certificate.id],
                data={'screen_preview': True},
            )[0]
            if isinstance(html, bytes):
                html = html.decode('utf-8', errors='replace')
            # Bandeau + bouton d'impression (Ctrl+P -> Enregistrer en PDF)
            banner = (
                "<div style='background:#4F46E5;color:#fff;padding:10px 16px;"
                "text-align:center;font-family:system-ui,sans-serif;'>"
                "Le PDF n'est pas disponible sur ce serveur (wkhtmltopdf manquant). "
                "<button onclick='window.print()' style='margin-left:10px;"
                "background:#fff;color:#4F46E5;border:none;border-radius:8px;"
                "padding:6px 14px;font-weight:700;cursor:pointer;'>"
                "Imprimer / Enregistrer en PDF</button></div>"
            )
            if '<body>' in html:
                html = html.replace('<body>', '<body>' + banner, 1)
            elif '<body' in html:
                # body avec attributs
                idx = html.find('>', html.find('<body'))
                html = html[:idx + 1] + banner + html[idx + 1:]
            else:
                html = banner + html
            return request.make_response(
                html, headers=[('Content-Type', 'text/html; charset=utf-8')])


class CertificatePublicVerify(http.Controller):
    """Verification publique de l'authenticite d'un certificat.

    Accessible sans authentification via le QR code imprime sur le PDF.
    L'URL contient un jeton aleatoire non devinable (pas le numero
    sequentiel), ce qui empeche de deviner les certificats des autres.
    """

    @http.route(
        '/certificate/verify/<string:token>',
        type='http', auth='public', website=True, sitemap=False,
    )
    def certificate_verify(self, token, **kw):
        certificate = request.env['exam.certificate'].sudo().search(
            [('verification_token', '=', token)], limit=1,
        )
        # Un certificat n'est "authentique" que s'il existe ET est approuve.
        valid = bool(certificate) and certificate.state == 'approved'
        values = {
            'certificate': certificate if valid else False,
            'valid': valid,
            'exists': bool(certificate),
            'state': certificate.state if certificate else False,
        }
        return request.render(
            'digii_exam_manager.certificate_verify_page', values,
        )
