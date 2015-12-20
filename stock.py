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
from openerp import netsvc

#----------------------------------------------------------
# Stock Move
#----------------------------------------------------------
class stock_move(osv.osv):
    _inherit = "stock.move"

    """
    Create a link between the invoice line and source move plus update the invoice line cost from the move
    cost so they are always the same. This avoids the problem of a return which is at the originating cost but
    the invoice line is at the current average cost.
    """

    def _create_invoice_line_from_vals(self, cr, uid, move, invoice_line_vals, context=None):
        invoice_line_vals.update({"move_id": move.id,
                                  "cost_price": move.price_unit})
        invoice_line = super(stock_move, self)._create_invoice_line_from_vals(cr, uid, move, invoice_line_vals, context=context)
        return invoice_line


class stock_picking(osv.osv):
    _inherit = "stock.picking"
    _columns = {
        'invoice_ids': fields.many2many('account.invoice', 'picking_invoice_rel', 'picking_id', 'invoice_id', 'Invoices'),
        'client_order_ref'  : fields.related ('sale_id', 'client_order_ref', type="char", relation="sale.order", string="Client Ref", readonly=True),
    }
    _description = "Picking List"

    def confirm_stock_account_input(self, cr, uid, picking_id, res, context=None):
        """ if this is a direct ship  or is a product line and the product is a type of service
            then do not change account at line level as there will be no stock journal created.
            This function is used for purchasing """

        for inv in self.pool.get('account.invoice').browse(cr, uid, res, context=context):
            for ol in inv.invoice_line:
                if ol.product_id:
                    if ol.move_id.location_dest_id.usage == 'customer' or (ol.product_id and ol.product_id.product_tmpl_id.type == 'service'):
                        continue

                    oa = ol.product_id.product_tmpl_id.property_stock_account_input and ol.product_id.product_tmpl_id.property_stock_account_input.id
                    if not oa:
                        oa = ol.product_id.categ_id.property_stock_account_input_categ and ol.product_id.categ_id.property_stock_account_input_categ.id
                    if oa:
                        fpos = ol.invoice_id.fiscal_position or False
                        a = self.pool.get('account.fiscal.position').map_account(cr, uid, fpos, oa)
                        self.pool.get('account.invoice.line').write(cr, uid, [ol.id], {'account_id': a})

        return res, picking_id


    def action_invoice_create(self, cr, uid, ids, journal_id=False, group=False,
            type='out_invoice', context=None):

        if not isinstance (ids, list):
            ids = [ids]
        res = super(stock_picking, self).action_invoice_create(cr, uid, ids, journal_id, group, type, context=context)
        if not res:
            return res

        if type == 'in_refund' or type == 'in_invoice':
            res, ids = self.confirm_stock_account_input(cr, uid, ids, res, context=context)

        return res

    def _prepare_service_invoice_line_purchase(self, cr, uid, group, picking, po_line, invoice_id, context=None):
        if group:
            name = (picking.name or '')
        else:
            name = po_line.order_id.name
        origin = ''

        account_id = po_line.product_id.property_account_expense.id
        if not account_id:
            account_id = po_line.product_id.categ_id.\
                    property_account_expense_categ.id
        invoice_obj = self.pool.get('account.invoice')
        invoice = invoice_obj.browse(cr, uid, invoice_id, context=context)

        if invoice.fiscal_position:
            fp_obj = self.pool.get('account.fiscal.position')
            fiscal_position = fp_obj.browse(cr, uid, invoice.fiscal_position.id, context=context)
            account_id = fp_obj.map_account(cr, uid, fiscal_position, account_id)
        uos_id = po_line.product_uom.id

        return {
            'name': name,
            'origin': origin,
            'invoice_id': invoice_id,
            'uos_id': uos_id,
            'product_id': po_line.product_id.id,
            'account_id': account_id,
            'price_unit': po_line.price_unit,
            'discount': 0.0,
            'quantity': po_line.product_qty,
            'invoice_line_tax_id': [(6, 0, [x.id for x in po_line.taxes_id])],
            'account_analytic_id': po_line.account_analytic_id.id,
        }


    def copy(self, cr, uid, id, default=None, context=None):
        if default is None:
            default = {}
        default = default.copy()
        default.update({'invoice_ids': [], })
        return super(stock_picking, self).copy(cr, uid, id, default, context)

stock_picking()

class product_product(osv.osv):
    _inherit = "product.product"

    def do_change_standard_price(self, cr, uid, ids, new_price, context=None):
        """ Changes the Standard Price of Product and creates an account move accordingly."""

        """ this is a copy and paste from stock/product
            the non-inventory leg of the journal should go to price variance account
            bug logged 1174045 - once fixed should be able to go back to core

        """

        location_obj = self.pool.get('stock.location')
        move_obj = self.pool.get('account.move')
        move_line_obj = self.pool.get('account.move.line')
        if context is None:
            context = {}
        user_company_id = self.pool.get('res.users').browse(cr, uid, uid, context=context).company_id.id
        loc_ids = location_obj.search(cr, uid, [('usage', '=', 'internal'), ('company_id', '=', user_company_id)])
        for rec_id in ids:
            datas = self.get_product_accounts(cr, uid, rec_id, context=context)
            for location in location_obj.browse(cr, uid, loc_ids, context=context):
                c = context.copy()
                c.update({'location': location.id, 'compute_child': False})
                product = self.browse(cr, uid, rec_id, context=c)

                price_difference_account = product.property_account_creditor_price_difference.id
                if not price_difference_account:
                    price_difference_account = product.product_tmpl_id.categ_id.property_account_creditor_price_difference_categ.id
                if not price_difference_account:
                    raise osv.except_osv(('Error!'), ('There is no price difference account defined ' \
                            'for this product: "%s" (id: %d)') % (self.name, self.id,))

                diff = product.standard_price - new_price
                if not diff:
                    raise osv.except_osv(_('Error!'), _("No difference between standard price and new price!"))
                qty = product.qty_available
                if qty:
                    # Accounting Entries
                    move_vals = {
                        'journal_id': datas['stock_journal'],
                        'company_id': location.company_id.id,
                    }
                    move_id = move_obj.create(cr, uid, move_vals, context=context)

                    if diff > 0:
                        amount_diff = qty * diff
                        debit_account_id = datas['price_difference_account']
                        credit_account_id = datas['property_stock_valuation_account_id']
                    else:
                        amount_diff = qty * -diff
                        debit_account_id = datas['property_stock_valuation_account_id']
                        credit_account_id = datas['price_difference_account']

                    move_line_obj.create(cr, uid, {
                                    'name': _('Standard Price changed'),
                                    'account_id': debit_account_id,
                                    'debit': amount_diff,
                                    'credit': 0,
                                    'move_id': move_id,
                                    }, context=context)
                    move_line_obj.create(cr, uid, {
                                    'name': _('Standard Price changed'),
                                    'account_id': credit_account_id,
                                    'debit': 0,
                                    'credit': amount_diff,
                                    'move_id': move_id
                                    }, context=context)
            self.write(cr, uid, rec_id, {'standard_price': new_price})
        return True


    def get_product_accounts(self, cr, uid, product_id, context=None):
        """
        Copy & paste from original as need to get the stock expense account as well for accounting entries

        To get the stock input account, stock output account, stock expense account and stock journal related to product.
        @param product_id: product id
        @return: dictionary which contains information regarding stock input account, stock output account, stock expense and stock journal
        """
        if context is None:
            context = {}
        product_obj = self.pool.get('product.product').browse(cr, uid, product_id, context=context)

        stock_input_acc = product_obj.property_stock_account_input and product_obj.property_stock_account_input.id or False
        if not stock_input_acc:
            stock_input_acc = product_obj.categ_id.property_stock_account_input_categ and product_obj.categ_id.property_stock_account_input_categ.id or False

        stock_output_acc = product_obj.property_stock_account_output and product_obj.property_stock_account_output.id or False
        if not stock_output_acc:
            stock_output_acc = product_obj.categ_id.property_stock_account_output_categ and product_obj.categ_id.property_stock_account_output_categ.id or False

        stock_expense_acc = product_obj.property_account_expense and product_obj.property_account_expense.id or False
        if not stock_expense_acc:
            stock_expense_acc = product_obj.categ_id.property_account_expense_categ and product_obj.categ_id.property_account_expense_categ.id or False

        journal_id = product_obj.categ_id.property_stock_journal and product_obj.categ_id.property_stock_journal.id or False
        account_valuation = product_obj.categ_id.property_stock_valuation_account_id and product_obj.categ_id.property_stock_valuation_account_id.id or False

        if not all([stock_input_acc, stock_output_acc, account_valuation, journal_id]):
            raise osv.except_osv(('Error!'), ('''One of the following information is missing on the product or product category and prevents the accounting valuation entries to be created:
                Product: %s
                Stock Input Account: %s
                Stock Output Account: %s
                Stock Valuation Account: %s
                Stock Expense Account: %s
                Stock Journal: %s
                ''') % (product_obj.name, stock_input_acc, stock_output_acc, account_valuation, stock_expense_acc, journal_id))

        return {
            'stock_account_input': stock_input_acc,
            'stock_account_output': stock_output_acc,
            'stock_expense_account': stock_expense_acc,
            'stock_journal': journal_id,
            'property_stock_valuation': account_valuation
        }




class stock_quant(osv.osv):

    _inherit = "stock.quant"


    '''
    Odoo decided that all real-time entries would be done at a quant level even if average cost product not FIFO.
    As a result we end up with potentially lots of stock move entries for a single stock move.
    While annoying the result matches and fixing would mean even more changes to core modules so have left as is.

    In addition we now add a link from the stock move to the account move line so we can reconcile the suspense accounts
    '''


    def _prepare_account_move_line(self, cr, uid, move, qty, cost, credit_account_id, debit_account_id, context=None):
        """
        Generate the account.move.line values to post to track the stock valuation difference due to the
        processing of the given quant.
        This is a copy and paste from certified module as logic for handling an average cost item is not correct.
        The core has:
            valuation_amount = move.location_id.usage != 'internal' and move.location_dest_id.usage == 'internal' and cost or move.product_id.standard_price
        but if the cost method is average then we can just use the cost from the stock move and if none the standard price
        NOTE - there is an entry PER QUANT - trying to roll back to move level meant too many changes so have left as is
        ALSO, put TRY in to fix issue where customers change company and causing security proble. Needs a proper fix so
        will log with odoo
        """
        if context is None:
            context = {}
        currency_obj = self.pool.get('res.currency')
        if context.get('force_valuation_amount'):
            valuation_amount = context.get('force_valuation_amount')
        else:
            if move.product_id.cost_method == 'average':
                if move.price_unit:
                    valuation_amount = move.price_unit
                elif move.product_id:
                    valuation_amount = move.product_id.standard_price
                else:
                    0.0
            else:
                valuation_amount = move.product_id.cost_method == 'real' and cost or move.product_id.standard_price
        # the standard_price of the product may be in another decimal precision, or not compatible with the coinage of
        # the company currency... so we need to use round() before creating the accounting entries.
        valuation_amount = currency_obj.round(cr, uid, move.company_id.currency_id, valuation_amount * qty)
        try:
            partner_id = (move.picking_id.partner_id and self.pool.get('res.partner')._find_accounting_partner(move.picking_id.partner_id).id) or False
        except:
            partner_id = False
        debit_line_vals = {
                    'name': move.name,
                    'product_id': move.product_id.id,
                    'quantity': qty,
                    'product_uom_id': move.product_id.uom_id.id,
                    'ref': move.picking_id and move.picking_id.name or False,
                    'date': move.date,
                    'partner_id': partner_id,
                    'debit': valuation_amount > 0 and valuation_amount or 0,
                    'credit': valuation_amount < 0 and -valuation_amount or 0,
                    'account_id': debit_account_id,
                    'stock_move_id':move.id
        }
        credit_line_vals = {
                    'name': move.name,
                    'product_id': move.product_id.id,
                    'quantity': qty,
                    'product_uom_id': move.product_id.uom_id.id,
                    'ref': move.picking_id and move.picking_id.name or False,
                    'date': move.date,
                    'partner_id': partner_id,
                    'credit': valuation_amount > 0 and valuation_amount or 0,
                    'debit': valuation_amount < 0 and -valuation_amount or 0,
                    'account_id': credit_account_id,
                    'stock_move_id':move.id
        }
        return [(0, 0, debit_line_vals), (0, 0, credit_line_vals)]

    def _account_entry_move(self, cr, uid, quants, move, context=None):
        """
        Accounting Valuation Entries

        This is a copy and paste as there are multiple move options that are not covered properly by the standard logic.

        quants: browse record list of Quants to create accounting valuation entries for. Unempty and all quants are supposed to have the same location id (thay already moved in)
        move: Move to use. browse record
        """
        if context is None:
            context = {}
        location_obj = self.pool.get('stock.location')
        location_from = move.location_id
        location_to = quants[0].location_id
        company_from = location_obj._location_owner(cr, uid, location_from, context=context)
        company_to = location_obj._location_owner(cr, uid, location_to, context=context)

        if not company_from:
            company_from = self.pool.get('res.users').browse(cr, uid, uid, context=context).company_id
        if not company_to:
            company_to = self.pool.get('res.users').browse(cr, uid, uid, context=context).company_id

        if move.product_id.valuation != 'real_time':
            return False
        for q in quants:
            if q.owner_id:
                # if the quant isn't owned by the company, we don't make any valuation entry
                return False
            if q.qty <= 0:
                # we don't make any stock valuation for negative quants because the valuation is already made for the counterpart.
                # At that time the valuation will be made at the product cost price and afterward there will be new accounting entries
                # to make the adjustments when we know the real cost price.
                return False



        # in case of routes making the link between several warehouse of the same company, the transit location belongs to this company, so we don't need to create accounting entries

        if context is None:
            context = {}
        src_company_ctx = dict(context, force_company=move.location_id.company_id.id)
        dest_company_ctx = dict(context, force_company=move.location_dest_id.company_id.id)
        account_moves = []
        ctx = context.copy()

        # Outgoing moves for a customer
        if move.location_id.usage == 'internal' and move.location_dest_id.usage == 'customer':
            ctx['force_company'] = company_from.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, src_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_valuation, acc_dest, journal_id, context=ctx))]

        # Incoming moves for a customer where an invoice is being generated
        elif move.location_id.usage == 'customer' and move.location_dest_id.usage == 'internal' \
            and move.picking_id.invoice_state == '2binvoiced':
            ctx['force_company'] = company_from.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, src_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_dest, acc_valuation, journal_id, context=ctx))]

        # Incoming moves for a customer where an invoice is not being generated
        elif move.location_id.usage == 'customer' and move.location_dest_id.usage == 'internal' \
            and move.picking_id.invoice_state != '2binvoiced':
            ctx['force_company'] = company_from.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, src_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_exp, acc_valuation, journal_id, context=ctx))]

        # Incoming moves for a supplier
        elif move.location_id.usage == 'supplier' and move.location_dest_id.usage == 'internal':
            ctx['force_company'] = company_to.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_src, acc_valuation, journal_id, context=ctx))]

        # Outgoing moves for a supplier where a credit invoice is being generated
        elif move.location_id.usage == 'internal' and move.location_dest_id.usage == 'supplier'\
            and move.picking_id.invoice_state == '2binvoiced':
            ctx['force_company'] = company_to.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_valuation, acc_src, journal_id, context=ctx))]

        # Outgoing moves for a supplier where an invoice is not being generated
        elif move.location_id.usage == 'internal' and move.location_dest_id.usage == 'supplier'\
            and move.picking_id.invoice_state != '2binvoiced':
            ctx['force_company'] = company_to.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_valuation, acc_exp, journal_id, context=ctx))]

        # Ingoing moves for a production order
        # this code works correctly if the GL account for the COS to be posted to is specified in the production location setup
        elif move.location_id.usage == 'internal' and move.location_dest_id.usage == 'production':
            ctx['force_company'] = company_to.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_valuation, acc_dest, journal_id, context=ctx))]

        # Outgoing moves for a production order
        elif move.location_id.usage == 'production' and move.location_dest_id.usage == 'internal':
            ctx['force_company'] = company_to.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_src, acc_valuation, journal_id, context=ctx))]

        # Stock-take accounting for count > soh
        elif move.location_id.usage == 'inventory' and move.location_dest_id.usage == 'internal':
            ctx['force_company'] = company_to.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_exp, acc_valuation, journal_id, context=ctx))]

        # Stock-take accounting for count < soh
        elif move.location_id.usage == 'internal' and move.location_dest_id.usage == 'inventory':
            ctx['force_company'] = company_to.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_valuation , acc_exp, journal_id, context=ctx))]

        # cross-company output part
        elif move.location_id.company_id \
            and move.location_id.company_id != move.location_dest_id.company_id:
            ctx['force_company'] = company_from.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, src_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_valuation, acc_dest, journal_id, context=ctx))]

        # cross-company input part
        elif move.location_id.company_id \
            and move.location_id.company_id != move.location_dest_id.company_id:
            ctx['force_company'] = company_to.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_valuation, acc_src, journal_id, context=ctx))]

        # handle a direct ship from supplier to customer. Assumes that the supplier invoice and customer invoice will create the offsetting entries
        elif move.location_id.usage == 'supplier' and move.location_dest_id.usage == 'customer':
            ctx['force_company'] = company_from.id
            journal_id, acc_src, acc_dest, acc_exp, acc_valuation = self._get_accounting_data_for_valuation(cr, uid, move, dest_company_ctx)
            account_moves += [(journal_id, self._create_account_move_line(cr, uid, quants, move, acc_src, acc_dest, journal_id, context=ctx))]




    def _get_accounting_data_for_valuation(self, cr, uid, move, context=None):
        """
        This is a copy & paste of original code to add stock_expense_account which is missing
        from standard openerp.

        Return the accounts and journal to use to post Journal Entries for the real-time
        valuation of the move.

        :param context: context dictionary that can explicitly mention the company to consider via the 'force_company' key
        :raise: osv.except_osv() is any mandatory account or journal is not defined.
        """
        product_obj = self.pool.get('product.product')
        accounts = product_obj.get_product_accounts(cr, uid, move.product_id.id, context)
        if move.location_id.valuation_out_account_id:
            acc_src = move.location_id.valuation_out_account_id.id
        else:
            acc_src = accounts['stock_account_input']

        if move.location_dest_id.valuation_in_account_id:
            acc_dest = move.location_dest_id.valuation_in_account_id.id
        else:
            acc_dest = accounts['stock_account_output']

        acc_exp = accounts.get('stock_expense_account')
        acc_valuation = accounts.get('property_stock_valuation', False)
        journal_id = accounts['stock_journal']

        if acc_dest == acc_valuation:
            raise osv.except_osv(('Error!'), ('Can not create Journal Entry, Output Account defined on this product and Variant account on category of this product are same.'))

        if acc_src == acc_valuation:
            raise osv.except_osv(('Error!'), ('Can not create Journal Entry, Input Account defined on this product and Variant account on category of this product are same.'))

        if not acc_src:
            raise osv.except_osv(('Error!'), ('There is no stock input account defined for this product or its category: "%s" (id: %d)') % \
                                    (move.product_id.name, move.product_id.id,))
        if not acc_dest:
            raise osv.except_osv(('Error!'), ('There is no stock output account defined for this product or its category: "%s" (id: %d)') % \
                                    (move.product_id.name, move.product_id.id,))
        if not journal_id:
            raise osv.except_osv(('Error!'), ('There is no journal defined on the product category: "%s" (id: %d)') % \
                                    (move.product_id.categ_id.name, move.product_id.categ_id.id,))
        if not acc_valuation:
            raise osv.except_osv(('Error!'), ('There is no inventory valuation account defined on the product category: "%s" (id: %d)') % \
                                    (move.product_id.categ_id.name, move.product_id.categ_id.id,))
        return journal_id, acc_src, acc_dest, acc_exp, acc_valuation





# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
