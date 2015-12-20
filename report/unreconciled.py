# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2011- Solnet Solutions (<http://www.solnetsolutions.co.nz>).
#    Copyright (C) 2010 OpenERP S.A. http://www.openerp.com
#    $Id$
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import osv, fields
import xlsxwriter 
import StringIO
import base64
from openerp.addons.report_output_directory import report_path
import os.path
import openerp.api
from openerp import fields as Fields
from datetime import datetime, timedelta
from dateutil.parser import parse
from dateutil.relativedelta import relativedelta
from openerp import tools
from openerp.tools.float_utils import float_is_zero
import cStringIO
import logging
import openerp.report

class AngloSaxonUnreconciledReport(osv.TransientModel):
    """ Unreconciled transactions in clearing accounts
    """
    
    _name = 'anglo.saxon.unreconciled.report'
    
    _columns = {
                'report_name': fields.char(size=64, string='Report Name', readonly = True),
                'account_id': fields.many2one('account.account', 'Account'),
                "period_id":fields.many2one('account.period', 'Up To Period'),
                'data': fields.binary('Download File',readonly=True),
                }
    
    _defaults = {'report_name': 'Unreconciled Anglo-Saxon Transactions.xlsx',
                }
    
    def get_periods(self, cr, uid, period_id, context=None):
        period_obj = self.pool.get('account.period')
        company_id = self.pool.get('res.users').browse(cr, uid, uid, context=context). company_id.id
        periods = period_obj.search(cr, uid, [('date_stop','<=', period_id.date_stop),('company_id','=', company_id)], context=context)
        return periods
    
    def button_process(self, cr, uid, ids, context = None):
        """ Create the report.
        """
        wizard = self.browse(cr, uid, ids[0], context = context)
        data = StringIO.StringIO()
        
        workbook = xlsxwriter.Workbook(data, {'in_memory': True})
        worksheet = workbook.add_worksheet('Data')
        format_number = workbook.add_format({'num_format': '#,##0.00', 'align': 'right'})
        format_row = workbook.add_format({'text_wrap': True, 'bold':True})
        format_total_cell = workbook.add_format({'bold':True,'num_format': '#,##0.00', 'align': 'right'})
        
        row = 0
        cell = 0
        
        #write headings
        worksheet.write(0,0,'Date')
        worksheet.write(0,1,'Period')
        worksheet.write(0,2,'ID')
        worksheet.write(0,3,'Journal')
        worksheet.write(0,4,'Partner')
        worksheet.write(0,5,'Move_ID')
        worksheet.write(0,6,'Move Name')
        worksheet.write(0,7,'Name')
        worksheet.write(0,8,'Product ID')
        worksheet.write(0,9,'Product Name')
        worksheet.write(0,10,'Quantity')
        worksheet.write(0,11,'Dr-Cr')
        worksheet.write(0,12,'Invoice Number')
        worksheet.write(0,13,'Ref')
        worksheet.write(0,14,'Stock Move ID')
        row = 1
        
        periods = self.get_periods(cr, uid, wizard.period_id, context=context)
        account = [x.id for x in wizard.account_id]
        selection_sql = "select aml.date, ap.name, aml.id, aj.name, res.name,aml.move_id, am.name, aml.name, " + \
                 "aml.product_id, pp.name_template,aml.quantity, aml.debit - aml.credit, aml.invoice_number,aml.ref,aml.stock_move_id " + \
                 "from account_move_line aml join account_period ap on aml.period_id = ap.id " + \
                 "join account_journal aj on aml.journal_id = aj.id " + \
                 "left join res_partner res on aml.partner_id = res.id " + \
                 "left join account_move am on aml.move_id = am.id " + \
                 "left join product_product pp on aml.product_id = pp.id " + \
                 "left join stock_move sm on aml.stock_move_id = sm.id " + \
                 "where aml.account_id = %s and aml.period_id in %s " + \
                 "and aml.reconcile_id is null; "
        
        selection_sql = selection_sql % (wizard.account_id.id, tuple(periods))
         
        cr.execute(selection_sql)
        lines_to_process = cr.fetchall()
        
        for line in lines_to_process:
            worksheet.write(row,0,line[0])
            worksheet.write(row,1,line[1])
            worksheet.write(row,2,line[2])
            worksheet.write(row,3,line[3])
            worksheet.write(row,4,line[4])
            worksheet.write(row,5,line[5])
            worksheet.write(row,6,line[6])
            worksheet.write(row,7,line[7])
            worksheet.write(row,8,line[8])
            worksheet.write(row,9,line[9])
            worksheet.write(row,10,line[10])
            worksheet.write(row,11,line[11])
            worksheet.write(row,12,line[12])
            worksheet.write(row,13,line[13])
            worksheet.write(row,14,line[14])
            row+=1
            
        workbook.close()
        data.seek(0)
        output = base64.encodestring(data.read())
        self.write(cr, uid, ids, {'data': output}, context=context)
         
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'anglo.saxon.unreconciled.report',
            'view_mode': 'form',
            'view_type': 'form',
            'res_id': wizard.id,
            'target': 'new',}
            
            

        
        
        
        