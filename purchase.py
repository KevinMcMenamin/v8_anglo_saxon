# -*- encoding: utf-8 -*-
##############################################################################
#    
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2009 Tiny SPRL (<http://tiny.be>).
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

from openerp.osv import fields, osv
import logging

class purchase_order(osv.osv):
    _name = "purchase.order"
    _inherit = "purchase.order"
    _description = "Purchase Order"
    _logger = logging.getLogger('account_anglo_saxon_solnet.purchase_order')

    """"the standard code sets the gl account for the PO line to the product expense account
        but if this is for a stockable product that is NOT a direct ship then there will be a stock
        move created by the PO and when the goods are received the  property_stock_account_input will be credited
        so we need to set the account for the invoice line to the same account so that they offset.
    """ 
    def _prepare_inv_line(self, cr, uid, account_id, order_line, context=None):
        direct_ship = True
        line = super(purchase_order, self)._prepare_inv_line(cr, uid, account_id, order_line, context=context)
        if not order_line.order_id.dest_address_id:
            direct_ship = False
            
        if order_line.product_id and not order_line.product_id.type == 'service' and direct_ship == False :
            acc_id = order_line.product_id.property_stock_account_input and order_line.product_id.property_stock_account_input.id
            if not acc_id:
                acc_id = order_line.product_id.categ_id.property_stock_account_input_categ and order_line.product_id.categ_id.property_stock_account_input_categ.id
            if acc_id:
                fpos = order_line.order_id.fiscal_position or False
                new_account_id = self.pool.get('account.fiscal.position').map_account(cr, uid, fpos, acc_id)
                line.update({'account_id': new_account_id})
        return line
   
   
   
    def view_invoice(self, cr, uid, ids, context=None):
        '''
        This function is called by a PO that has invoice control based on PO lines.
        Need to overrride to add picking_inv_rel if PO has stock products
        #TODO - check on direct ship - may need to code for.
        '''
        mod_obj = self.pool.get('ir.model.data')
        wizard_obj = self.pool.get('purchase.order.line_invoice')
        #compute the number of invoices to display
        inv_ids = []
        for po in self.browse(cr, uid, ids, context=context):
            if po.invoice_method in ('manual','order'):
                if not po.invoice_ids:
                    context.update({'active_ids' :  [line.id for line in po.order_line]})
                    wizard_obj.makeInvoices(cr, uid, [], context=context)
        
        for po in self.browse(cr, uid, ids, context=context):
            inv_ids+= [invoice.id for invoice in po.invoice_ids]
        
        res = mod_obj.get_object_reference(cr, uid, 'account', 'invoice_supplier_form')
        res_id = res and res[1] or False

        return {
            'name': ('Supplier Invoices'),
            'view_type': 'form',
            'view_mode': 'form',
            'view_id': [res_id],
            'res_model': 'account.invoice',
            'context': "{'type':'in_invoice', 'journal_type': 'purchase'}",
            'type': 'ir.actions.act_window',
            'nodestroy': True,
            'target': 'current',
            'res_id': inv_ids and inv_ids[0] or False,
        }


class stock_picking(osv.osv):
    _inherit = 'stock.picking'
    _columns = {
        'purchase_id': fields.many2one('purchase.order', 'Purchase Order',
            ondelete='set null', select=True),
    }

    _defaults = {
        'purchase_id': False,
    }

class purchase_order_line(osv.osv):
    
    """
    this is to fix an error in certified module where invoice_lines is declared as a m2m
    but in account.invoice.line the other side is declared as a m2o
    """
    
    _inherit = 'purchase.order.line'
    _columns = {    
    
    'invoice_lines': fields.one2many('account.invoice.line', 'purchase_line_id', string='Invoice Line',
                                          readonly=True, copy=False),
                }

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
