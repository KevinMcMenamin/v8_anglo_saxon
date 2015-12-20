# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################


from openerp.osv import osv, fields
from openerp.tools.translate import _
from math import fabs
from openerp.addons.decimal_precision import get_precision
from openerp import api      
from openerp.api import Environment
from openerp.modules.registry import RegistryManager
import logging
from datetime import datetime

log = logging.getLogger(__name__)


class account_anglo_saxon_reconcile(osv.osv_memory):
    _name = 'account.anglo.saxon.reconcile'
    _description = 'Automatic Anglo Reconcile'

    _columns = {
        'awaiting_supplier_invoices': fields.many2one('account.account', 'Awaiting Supplier Invoices'),
        'to_be_invoiced': fields.many2one('account.account', 'To Be Invoiced'),
        'reconciled': fields.integer('Reconciled transactions', readonly=True),
        'unreconciled': fields.integer('Not reconciled transactions', readonly=True),
        "company_id": fields.many2one("res.company", "Company"),
    }

    _defaults = {
        "company_id": lambda obj, cr, uid, context: obj.pool.get('res.users').browse(cr, uid, uid, context).company_id.id,
        'awaiting_supplier_invoices':lambda obj, cr, uid, context: obj.pool.get('res.users').browse(cr, uid, uid, context).company_id.stock_input_account.id,
        'to_be_invoiced':lambda obj, cr, uid, context: obj.pool.get('res.users').browse(cr, uid, uid, context).company_id.stock_output_account.id,
    }
    
    def reconcile(self, cr, uid, context=None):
        if context is None:
            context = {}
        # form = self.read(cr, uid, ids, [])[0]
        res_users_obj = self.pool.get("res.users")
        company_id = res_users_obj.browse(cr, uid, uid).company_id
        awaiting_supplier_invoices = company_id.stock_input_account
        to_be_invoiced = company_id.stock_output_account
        if not awaiting_supplier_invoices or not to_be_invoiced:
            raise osv.except_osv(_('UserError'), _('You must select accounts to reconcile'))

        account_to_be_reconcilied = [awaiting_supplier_invoices,to_be_invoiced]
        if not account_to_be_reconcilied: 
            raise osv.except_osv(_('Error'), _('The account is not defined to be reconciled !'))
        for account in account_to_be_reconcilied:          
            cr.execute('select sum(debit), sum(credit), stock_move_id '\
                        'FROM account_move_line '\
                        'where account_id=%s and reconcile_id IS NULL and stock_move_id is not Null '\
                        'group by stock_move_id',(account.id,))

            ids=[]
            if cr.rowcount:
                for row in cr.fetchall():
                    sdebit = row[0] or 0.0
                    scredit = row[1] or 0.0
                    balance = fabs(sdebit-scredit)
                    if balance is not None and balance<= company_id.price_variance_writeoff_amount:
                        cr.execute('select id FROM account_move_line where account_id=%s and stock_move_id=%s',(account.id,row[2]))
                        if cr.rowcount:
                            for value in cr.fetchall():
                                ids.append(value[0])

            if ids:
                journal_obj = self.pool.get('account.journal').search(cr, uid, [('company_id', '=', company_id.id),('type', '=', 'general')], context=context)
                periods = self.pool.get('account.period').find(cr, uid)
                self.pool.get('account.move.line').reconcile(cr, uid, ids, type='auto', writeoff_acc_id=company_id.price_variance_writeoff_account.id, 
                                                             writeoff_period_id=periods[0], writeoff_journal_id=journal_obj[0], context=context)
                        

        return {'type': 'ir.actions.act_window.close'}
        
    @api.model
    def run_scheduled_servicing(self):
        """ Run Reconciliation Process.
        
            This method creates a new environment cursor for each call to action_process
        """
        start_time = datetime.now()
        log.info("run_anglo_saxon_reconcile_reconciliation: Start")
        with RegistryManager.get(self.env.cr.dbname, False, None, False).cursor() as cr:
            with Environment.manage():  # class function
                run_env = Environment(cr, self.env.user.id, self.env.context)
                processed_assets = self.with_env(run_env).reconcile()
        log.info(("run_anglo_saxon_reconcile_reconciliation: End.  Elapsed: {e}s, "
                 "Transaction Count: {ct}").format(e = (datetime.now() - start_time).total_seconds(),
                                                       ct = len(processed_assets))
                 )
         
account_anglo_saxon_reconcile()