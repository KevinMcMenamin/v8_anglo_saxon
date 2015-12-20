##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C)
#    2004-2010 Tiny SPRL (<http://tiny.be>).
#    2009-2010 Veritos (http://veritos.nl).
#    2013 Solnet Solutions Limited (http://solnetsolutions.co.nz
#    All Rights Reserved
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
# Known Issues
#
# Include stock_out_refund_patch if required in b8
# add link between invoice lines and moves
# check credits done through warehouse - do they have the originating so number passed through to the invoice
#
# Accounting decisions
#
# For a sale line that is for a service product, no COS entry will be created
#


import logging

from openerp import api
from openerp.osv import osv, fields
import openerp.addons.decimal_precision as dp


class account_invoice(osv.osv):

    _inherit = 'account.invoice'

    _columns = {
        "picking_ids": fields.many2many("stock.picking", "picking_invoice_rel", "invoice_id", "picking_id", "Pickings"),
    }

    """
    This needs to be done here for a financial credit as the journal lines are created before the compute_refund function is called
    Also need to clear any reference to purchase line or stock_move_id
    """

    def refund(self, cr, uid, invoice_list, date=None, period_id=None, description=None, journal_id=None, context=None):
        account_invoice_obj = self.pool.get('account.invoice')
        invoice_line_obj = self.pool.get('account.invoice.line')
        from_invoice_id = account_invoice_obj.browse(cr, uid, invoice_list[0], context=context)
        refund_id = super(account_invoice, self).refund(cr, uid, invoice_list, date, period_id, description, journal_id, context=context)
        refund_invoice = self.browse(cr, uid, refund_id, context=context)
        lines = refund_invoice.invoice_line
        for line in lines:
            if line.product_id:
                account = line.product_id.product_tmpl_id.property_account_expense.id
                if not account:
                    account = line.product_id.categ_id.property_account_expense_categ.id

                if account and refund_invoice.type == 'in_refund':
                    invoice_line_obj.write(cr, uid, line.id,
                                           {"account_id": account,
                                            "purchase_line_id": False,
                                            "move_id": False}, context=context)
                else:
                    invoice_line_obj.write(cr, uid, line.id,
                                           {"move_id": False}, context=context)

        return refund_id

    @api.model
    def line_get_convert(self, line, part, date):
        result = super(account_invoice, self).line_get_convert(line, part, date)
        if result:
            result['stock_move_id'] = line.get('stock_move_id', False)
        return result


class account_invoice_line(osv.osv):
    _inherit = "account.invoice.line"

    _columns = {
        'move_id': fields.many2one('stock.move', 'Stock Moves'),
        'cost_price': fields.float("Cost Price", type='float', digits_compute=dp.get_precision('Account')),
    }

    @api.model
    def move_line_get_item(self, line):
        result = super(account_invoice_line, self).move_line_get_item(line)
        if result:
            result['stock_move_id'] = line.move_id.id or False
        return result

    def move_line_get_get_price(self, cr, uid, inv, company_currency, i_line):
        cur_obj = self.pool.get('res.currency')
        if i_line.cost_price:
            cost_price = i_line.cost_price
        else:
            cost_price = i_line.product_id.product_tmpl_id.standard_price
        if inv.currency_id.id != company_currency:
            price = cur_obj.compute(cr, uid, company_currency, inv.currency_id.id, cost_price * i_line.quantity, context={'date': inv.date_invoice})
        else:
            price = cost_price * i_line.quantity
        return price

    def is_this_a_direct_delivery(self, cr, invoice_line):
        '''
        Check if invoice is for direct delivery.
        '''
        direct_ship = False
        if invoice_line.move_id:
            if invoice_line.move_id.procurement_id.purchase_line_id.order_id.dest_address_id:
                direct_ship = True
        return direct_ship

    def determine_debit_account_for_non_service_invoice_line(self, invoice_line, direct_ship):
        '''
        Given an invoice line that is not for a service product and a flag indicating whether the
        product is for direct delivery, this method returns the debit account to be used.
        '''
        dacc = False
        if direct_ship == True:  # debit account dacc will be the output account
            # first check the product, if empty check the category
            dacc = invoice_line.product_id.product_tmpl_id.property_stock_account_input and invoice_line.product_id.product_tmpl_id.property_stock_account_input.id
            if not dacc:
                dacc = invoice_line.product_id.categ_id.property_stock_account_input_categ and invoice_line.product_id.categ_id.property_stock_account_input_categ.id
        else:
            dacc = invoice_line.product_id.product_tmpl_id.property_stock_account_output and invoice_line.product_id.product_tmpl_id.property_stock_account_output.id
            if not dacc:
                dacc = invoice_line.product_id.categ_id.property_stock_account_output_categ and invoice_line.product_id.categ_id.property_stock_account_output_categ.id
        return dacc

    def determine_credit_account_for_non_service_invoice_line(self, invoice_line):
        '''
        Given an invoice line that is for a non-service product this method returns a
        credit account to be used.

        In both cases the credit account cacc will be the expense account,
        first check the product, if empty check the category
        '''
        cacc = invoice_line.product_id.product_tmpl_id.property_account_expense and invoice_line.product_id.product_tmpl_id.property_account_expense.id
        if not cacc:
            cacc = invoice_line.product_id.categ_id.property_account_expense_categ and invoice_line.product_id.categ_id.property_account_expense_categ.id
        return cacc

    def add_move_lines_for_non_service_invoice_line(self, dictionary_of_account_move_lines, invoice_line, debit_account_id, credit_account_id, price):
        '''
        Adds account move lines for debit account and credit account for service invoice line.
        New account move lines are added to the dictionary of account move lines.
        '''
        dictionary_of_account_move_lines.append({'type': 'src',
                                                 'name': invoice_line.name[:64],
                                                 'price_unit': invoice_line.product_id.product_tmpl_id.standard_price,
                                                 'quantity': invoice_line.quantity,
                                                 'price': price,
                                                 'account_id': debit_account_id,
                                                 'product_id': invoice_line.product_id.id,
                                                 'uos_id': invoice_line.uos_id.id,
                                                 'account_analytic_id': invoice_line.account_analytic_id.id or False,
                                                 'stock_move_id': invoice_line.move_id.id or False,
                                                 'taxes': invoice_line.invoice_line_tax_id})

        dictionary_of_account_move_lines.append({'type': 'src', 'name': invoice_line.name[:64],
                                                 'price_unit': invoice_line.product_id.product_tmpl_id.standard_price,
                                                 'quantity': invoice_line.quantity,
                                                 'price': -1 * price,
                                                 'account_id': credit_account_id,
                                                 'product_id': invoice_line.product_id.id,
                                                 'uos_id': invoice_line.uos_id.id,
                                                 'account_analytic_id': invoice_line.account_analytic_id.id or False,
                                                 'stock_move_id': invoice_line.move_id.id or False,
                                                 'taxes': invoice_line.invoice_line_tax_id})

        return dictionary_of_account_move_lines

    def is_invoice_line_on_sales_order(self, cr, invoice_line):
        """
        Check if the invoice line has a linked sale order line
        Return true if yes
        """
        invoice_line = invoice_line.id
        cr.execute("select order_line_id from sale_order_line_invoice_rel where invoice_id = %s", (invoice_line,))
        result = cr.fetchone()
        if result and len(result):
            return True
        else:
            return False

    def invoice_for_sales_order(self, cr, uid, dictionary_of_account_move_lines, inv, logger):
        '''
        This method handles creating account_move_lines for all invoices that have an invoice_type of 
        'out_invoice' or 'out_refund'

        need to check if direct delivery
        if so, then set dacc to stock input account as there will be no stock move journal
        this entry will offset the input account entry created from the supplier invoice
        TODO need to check what happens when the standard/average cost is <> buy price
        if this line is a service line then create no COS entries

        also need to check if this product has been added just on the invoice
        if so, then no COS entry
        '''

        logger.info('Handling invoices of with an invoice type of out_invoice or out_refund that are linked to a sales order.')
        company_currency = inv.company_id.currency_id.id
        for i_line in inv.invoice_line:
            logger.debug('Processing invoice line with id: ' + `i_line.id`)
            if i_line.product_id and not i_line.product_id.product_tmpl_id.type == 'service':

                direct_ship = self.is_this_a_direct_delivery(cr, i_line)
                if self.is_invoice_line_on_sales_order(cr, i_line):
                    dacc = self.determine_debit_account_for_non_service_invoice_line(i_line, direct_ship)
                    cacc = self.determine_credit_account_for_non_service_invoice_line(i_line)
                    if dacc and cacc:
                        price = self.move_line_get_get_price(cr, uid, inv, company_currency, i_line)
                        self.add_move_lines_for_non_service_invoice_line(dictionary_of_account_move_lines, i_line, dacc, cacc, price)

        return dictionary_of_account_move_lines

    def group_invoice_lines_according_to_product(self, inv):
        '''
        This method groups invoice lines according to the product
        that they are for.  It returns a dictionary which has
        product ids as key and and invoice lines as values.
        '''
        product_set = set([inv_line.product_id.id for inv_line in inv.invoice_line])
        product_inv_line_map = {}
        for product_id in product_set:
            product_inv_line_map[product_id] = [inv_line for inv_line in inv.invoice_line if inv_line.product_id and inv_line.product_id.id == product_id]

        return product_inv_line_map

    def get_stock_moves_for_invoiced_product(self, cr, uid, inv, product, context):
        '''
        Obtains the stock pickings from invoice and checks whether there are any
        stock moves for those stock pickings pertaining to the product specified.

        The method returns any move_ids that are found (or empty list if none are found).
        Note added check where PO = Based on generated draft invoice or Based on Purchase Order Lines
        In this case need to find all moves that are in a state of done related to the PO
        as picking_invoice_rel is not updated where there is a back-order if the PO is as above

        Also need to check for return and deal with differently.
        '''
        # TODO for a PO 'on order' it will create the picking and moves on confirm
        # plus the invoice, so we can write the picking_ids, move_ids then
        # ..what about back-orders - ie extra related moves
        # if the invoice has been created from a picking, then the move_ids are in the invoice_line record

        move_obj = self.pool.get('stock.move')
        picking_obj = self.pool.get('stock.picking')
        purchase_obj = self.pool.get('purchase.order')
        location_obj = self.pool.get('stock.location')
        select_sql = 'select purchase_id from purchase_invoice_rel where invoice_id = %s'
        select_sql = select_sql % (inv.id)
        cr.execute(select_sql)
        purchase_orders = [x[0] for x in cr.fetchall()]
        for purchase_order in purchase_orders:
            invoice_method = purchase_obj.browse(cr, uid, purchase_order, context=context).invoice_method
            continue

        # TODO check SO methods
        if invoice_method in ('order', 'manual'):
            company = inv.company_id.id
            supplier_location_id = location_obj.search(cr, uid, [('company_id', '=', company), ('usage', '=', 'supplier')])
            if not supplier_location_id:
                # TODO ideally should search based on company being null
                supplier_location_id = location_obj.search(cr, uid, [('usage', '=', 'supplier')])
            if inv.type == 'in_refund':
                move_ids = []
                picking_ids = []
                picking_ids = picking_obj.search(cr, uid, [('purchase_id', '=', purchase_order)])
                move_ids = move_obj.search(cr, uid, [('picking_id', 'in', picking_ids), ('product_id', '=', product.id), ('state', '=', 'done'), ('location_dest_id', 'in', supplier_location_id)],
                                           context=context)
            else:
                move_ids = []
                picking_ids = []
                picking_ids = picking_obj.search(cr, uid, [('purchase_id', '=', purchase_order)])
                move_ids = move_obj.search(cr, uid, [('picking_id', 'in', picking_ids), ('product_id', '=', product.id), ('state', '=', 'done'), ('location_id', 'in', supplier_location_id)],
                                           context=context)
        else:
            move_ids = []
            picking_ids = [pk.id for pk in inv.picking_ids]
            if len(picking_ids):
                move_ids = move_obj.search(cr, uid, [('picking_id', 'in', picking_ids), ('product_id', '=', product.id), ('state', '=', 'done')],
                                           context=context)
        return move_ids

    def determine_price_difference_account_from_product_or_category(self, product):
        acc = product.product_tmpl_id.property_account_creditor_price_difference and product.product_tmpl_id.property_account_creditor_price_difference.id
        if not acc:  # if not found on the product get the price difference account at the category
            acc = product.categ_id.property_account_creditor_price_difference_categ and product.categ_id.property_account_creditor_price_difference_categ.id
        return acc

    def for_in_determine_stock_input_account_from_product_or_category(self, product):
        # oa will be the stock input account irrespective if receipt or return
        # first check the product, if empty check the category
        oa = product.product_tmpl_id.property_stock_account_input and product.product_tmpl_id.property_stock_account_input.id
        if not oa:
            oa = product.categ_id.property_stock_account_input_categ and product.categ_id.property_stock_account_input_categ.id
        return oa

    def determine_fiscal_position_account_from_stock_input_account(self, cr, uid, inv, stock_input_account):
        fpos_account = None
        if stock_input_account:  # get the fiscal position
            fpos = inv.fiscal_position or False
            fpos_account = self.pool.get('account.fiscal.position').map_account(cr, uid, fpos, stock_input_account)
        return fpos_account

    def calculate_total_value_of_stock_moves(self, cr, uid, move_ids):
        move_value = 0.0
        move_obj = self.pool.get('stock.move')
        for move_line in move_obj.browse(cr, uid, move_ids):  # TODO
            move_value += move_line.price_unit * move_line.product_qty

        return move_value

    def create_move_lines_for_difference(self, account_move_lines_for_price_difference, product_invoice_quantity,
                                         product, debit_account, credit_account, account_analytic, price_diff, invoice_line):
        # P&L

        account_move_lines_for_price_difference.append({'type': 'src',
                                                        'name': product.name[:64],
                                                        'price_unit': price_diff,
                                                        'quantity': product_invoice_quantity,
                                                        'price': price_diff,
                                                        'account_id': debit_account,
                                                        'product_id': product.id,
                                                        'uos_id': product.uos_id.id,
                                                        'account_analytic_id': account_analytic.id,
                                                        'stock_move_id': invoice_line.move_id.id or False,
                                                        'taxes': []})

        # Input valuation
        account_move_lines_for_price_difference.append({'type': 'src',
                                                        'name': product.name[:64],
                                                        'price_unit': price_diff,
                                                        'quantity': product_invoice_quantity,
                                                        'price': 0 - price_diff,
                                                        'account_id': credit_account,
                                                        'product_id': product.id,
                                                        'uos_id': product.uos_id.id,
                                                        'account_analytic_id': '',
                                                        'stock_move_id': invoice_line.move_id.id or False,
                                                        'taxes': []})

        return account_move_lines_for_price_difference

    def convert_difference_to_invoice_currency(self, cr, uid, difference, inv, invoice_line, context=None):
        cur_obj = self.pool.get('res.currency')
        from_currency = inv.currency_id.id
        to_currency = self.pool.get('res.users').browse(cr, uid, uid, context=context).company_id.currency_id.id
        if invoice_line.purchase_line_id.order_id.forward_exchange_contract:
            rate = invoice_line.purchase_line_id.order_id.forward_exchange_contract.rate
        else:
            rate = cur_obj.compute(cr, uid, to_currency, from_currency, 1, context={'date': inv.date_invoice})
        if rate:
            difference = difference * rate

        return difference

    def convert_purchase_line_to_invoice_currency(self, cr, uid, inv, invoice_line, context=None):
        cur_obj = self.pool.get('res.currency')
        to_currency = inv.currency_id.id
        from_currency = invoice_line.purchase_line_id.order_id.currency_id.id
        purchase_price_unit = invoice_line.purchase_line_id.price_unit
        if invoice_line.purchase_line_id.order_id.forward_exchange_contract:
            rate = invoice_line.purchase_line_id.order_id.forward_exchange_contract.rate
        else:
            rate = cur_obj.compute(cr, uid, to_currency, from_currency, 1, context={'date': inv.date_invoice})
        if rate:
            purchase_price_unit = invoice_line.purchase_line_id.price_unit / rate

        return purchase_price_unit

    def invoice_for_purchase_order(self, cr, uid, inv, dict_account_move_lines, context, logger):
        '''
        since the stock move cost price cannot be changed by the user, the only potential price difference
        arises where the price on the invoice line is different from the price on the PO.
        if we take any price difference * the invoice quantity then this will cater for any back-order situation
        as long as the full quantity is received.
        we do have an issue if the PO is invoice from order and the quantity actually received <> the order quantity
        but just going to have to live with that as we cannot know if there will be more receipts at some point in the future 

        If the supplier invoice is not in local currency we don't need to do anything as the difference is based on the PO currency
        versus the invoice currency and these should be the same. The conversion to local currency happens later.

        If they are not we need to convert the PO currency to the invoice currency

        '''

        for line in inv.invoice_line:
            if (line.product_id and line.purchase_line_id and
                    line.purchase_line_id.price_unit != line.price_unit):
                account_move_lines_for_price_difference = []
                if line.purchase_line_id.order_id.currency_id != line.invoice_id.currency_id:
                    purchase_price_unit = self.convert_purchase_line_to_invoice_currency(cr, uid, inv, line, context=context)
                else:
                    purchase_price_unit = line.purchase_line_id.price_unit

                difference = line.quantity * (purchase_price_unit - line.price_unit)
                acc = self.determine_price_difference_account_from_product_or_category(line.product_id)
                stock_input_account = self.for_in_determine_stock_input_account_from_product_or_category(line.product_id)
                fpos_account = self.determine_fiscal_position_account_from_stock_input_account(cr, uid, inv, stock_input_account)
                account_analytic = line.account_analytic_id
                if abs(difference) > 0.01:
                    self.create_move_lines_for_difference(account_move_lines_for_price_difference, line.quantity, line.product_id,
                                                          fpos_account, acc, account_analytic, difference, line)
                else:
                    self.create_move_lines_for_difference(account_move_lines_for_price_difference, line.quantity, line.product_id, acc,
                                                          fpos_account, account_analytic, abs(difference), line)
                dict_account_move_lines += account_move_lines_for_price_difference

        return dict_account_move_lines

    def calculate_line_in_local_currency(self, cr, uid, inv, invoice_line, context=None):
        cur_obj = self.pool.get('res.currency')
        from_currency = inv.currency_id.id
        to_currency = self.pool.get('res.users').browse(cr, uid, uid, context=context).company_id.currency_id.id
        if invoice_line.purchase_line_id.order_id.forward_exchange_contract:
            rate = invoice_line.purchase_line_id.order_id.forward_exchange_contract.rate
        elif from_currency != to_currency:
            rate = cur_obj.compute(cr, uid, to_currency, from_currency, 1, context={'date': inv.date_invoice})
        else:
            rate = 1.0
        line_price_unit = (invoice_line.price_unit - (invoice_line.price_unit * invoice_line.discount / 100)) / rate

        return line_price_unit

    def invoice_for_purchase_refund(self, cr, uid, inv, dict_account_move_lines, context, logger):
        '''
        since the stock move cost price cannot be changed by the user, the only potential price difference
        arises where the price - discount on the invoice line is different from the price on the PO.
        if we take any price difference * the invoice quantity then this will cater for any back-order situation
        as long as the full quantity is received.

        But also need to cater for a currency difference. The move will always be in company currency but the invoice
        could be changed to be in the supplier currency. The difference has to be calcuated in invoice currency
        as converted later to company currency

        If the line does not have a move_id then we this means either it is a service line or the user has added manually.
        In either case there will be no move to offset so the GL account can be left as the expense account

        '''

        for line in inv.invoice_line:
            line_price_unit = self.calculate_line_in_local_currency(cr, uid, inv, line, context=context)
            if line.move_id and line.move_id.price_unit <> line_price_unit:
                account_move_lines_for_price_difference = []
                difference = line.quantity * (line.move_id.price_unit - line_price_unit)
                if abs(difference) > 0.01:
                    if inv.currency_id.id != self.pool.get('res.users').browse(cr, uid, uid, context=context).company_id.currency_id.id:
                        difference = self.convert_difference_to_invoice_currency(cr, uid, difference, inv, line, context=context)
                    acc = self.determine_price_difference_account_from_product_or_category(line.product_id)
                    stock_input_account = self.for_in_determine_stock_input_account_from_product_or_category(line.product_id)
                    fpos_account = self.determine_fiscal_position_account_from_stock_input_account(cr, uid, inv, stock_input_account)
                    account_analytic = line.account_analytic_id
                    if difference > 0:
                        self.create_move_lines_for_difference(account_move_lines_for_price_difference, line.quantity, line.product_id,
                                                              fpos_account, acc, account_analytic, difference, line)
                    else:
                        self.create_move_lines_for_difference(account_move_lines_for_price_difference, line.quantity, line.product_id, acc,
                                                              fpos_account, account_analytic, abs(difference), line)
                    dict_account_move_lines += account_move_lines_for_price_difference

        return dict_account_move_lines

    def check_if_invoice_is_for_purchase_order(self, cr, invoice_id):
        po_inv_rel = False
        cr.execute("select invoice_id from purchase_invoice_rel where invoice_id = %s", (invoice_id,))
        result = cr.fetchone()
        if result:
            po_inv_rel = True
        return po_inv_rel

    def check_if_invoice_is_for_purchase_return(self, cr, uid, invoice_id, context=None):
        po_return_inv = False
        invoice = self.pool.get('account.invoice').browse(cr, uid, [invoice_id], context=context)
        for line in invoice.invoice_line:
            if line.move_id:
                po_return_inv = True
                return po_return_inv
        return po_return_inv

    def check_if_invoice_is_for_sale_order(self, cr, invoice_id):
        so_inv_rel = False
        cr.execute("select invoice_id from sale_order_invoice_rel where invoice_id = %s", (invoice_id,))
        result = cr.fetchone()
        if result:
            so_inv_rel = True
        if not so_inv_rel:
            cr.execute("select invoice_id from pos_order where invoice_id = %s", (invoice_id,))
            result = cr.fetchone()
            if result:
                so_inv_rel = True
        return so_inv_rel

    def move_line_get(self, cr, uid, invoice_id, context=None):
        '''
            #this now incorporates the fix for serialised products as per account_anglo_saxon_shipment_costing_patch
            #plus the fix identified by ferdinand at camp2camp
            #code now caters for
            # - an invoice (in or out) for a stockable product where there is no associated move
            # - direct ship of purchased products to a customer
        '''
        logger = logging.getLogger('account_anglo_saxon_solnet.move_line_get')
        dict_account_move_lines = super(account_invoice_line, self).move_line_get(cr, uid, invoice_id, context=context)
        inv = self.pool.get('account.invoice').browse(cr, uid, invoice_id, context=context)

        # this section below is changed from the original to cater for an invoice that has not been generated from a sales order
        # in this circumstance there is no output account entry to be offset to

        po_inv_rel = self.check_if_invoice_is_for_purchase_order(cr, invoice_id)
        so_inv_rel = self.check_if_invoice_is_for_sale_order(cr, invoice_id)
        po_return_inv = self.check_if_invoice_is_for_purchase_return(cr, uid, invoice_id, context=context)
        if inv.type in ('out_invoice', 'out_refund') and so_inv_rel:
            self.invoice_for_sales_order(cr, uid, dict_account_move_lines, inv, logger)
        elif inv.type == 'in_invoice' and po_inv_rel:
            self.invoice_for_purchase_order(cr, uid, inv, dict_account_move_lines, context, logger)
        elif inv.type == 'in_refund' and po_return_inv:
            self.invoice_for_purchase_refund(cr, uid, inv, dict_account_move_lines, context, logger)

        return dict_account_move_lines


# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
