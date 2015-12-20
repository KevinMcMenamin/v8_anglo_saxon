
from openerp.osv import osv, fields
import logging

class purchase_line_invoice(osv.osv_memory):
    
    """
             This is a straight copy & paste from the purchase module
             as the coding is wrong. when a PO has a type of invoice from order
             but is for a stock line it needs to go to the stock input account
             or when the goods are received there is no off-setting entry,
             but when the product type = service, needs to go to expense.
             The standard module now deals with product but not service.
    """
        
        
    _inherit = 'purchase.order.line_invoice'
    

    def build_line(self,cr, uid, a, line, context=None):
        try:
            a.id
            account_id = a.id
        except:
            account_id = a
            
        res = {
            'name':line.name, 
            'origin':line.order_id.name, 
            'account_id':account_id, 
            'price_unit':line.price_unit, 
            'quantity':line.product_qty, 
            'uos_id':line.product_uom.id, 
            'product_id':line.product_id.id or False, 
            'invoice_line_tax_id':[(6, 0, [x.id for x in line.taxes_id])], 
            'account_analytic_id':line.account_analytic_id and line.account_analytic_id.id or False}
        return res

    def makeInvoices(self, cr, uid, ids, context=None):

       

        if context is None:
            context={}

        record_ids =  context.get('active_ids',[])
        if record_ids:
            res = False
            invoices = {}
            invoice_obj=self.pool.get('account.invoice')
            purchase_line_obj=self.pool.get('purchase.order.line')
            property_obj=self.pool.get('ir.property')
            account_fiscal_obj=self.pool.get('account.fiscal.position')
            invoice_line_obj=self.pool.get('account.invoice.line')
            account_jrnl_obj=self.pool.get('account.journal')

            def multiple_order_invoice_notes(orders):
                notes = ""
                for order in orders:
                    notes += "%s \n" % order.notes
                return notes



            def make_invoice_by_partner(partner, orders, lines_ids):
                """
                    create a new invoice for one supplier
                    @param partner : The object partner
                    @param orders : The set of orders to add in the invoice
                    @param lines : The list of line's id
                """
                name = orders and orders[0].name or ''
                journal_id = account_jrnl_obj.search(cr, uid, [('type', '=', 'purchase')], context=None)
                journal_id = journal_id and journal_id[0] or False
                a = partner.property_account_payable.id
                inv = {
                    'name': name,
                    'origin': name,
                    'type': 'in_invoice',
                    'journal_id':journal_id,
                    'reference' : partner.ref,
                    'account_id': a,
                    'partner_id': partner.id,
                    'invoice_line': [(6,0,lines_ids)],
                    'currency_id' : orders[0].pricelist_id.currency_id.id,
                    'comment': multiple_order_invoice_notes(orders),
                    'payment_term': orders[0].payment_term_id.id,
                    'fiscal_position': partner.property_account_position.id
                }
                inv_id = invoice_obj.create(cr, uid, inv)
                for order in orders:
                    order.write({'invoice_ids': [(4, inv_id)]})
                return inv_id

            for line in purchase_line_obj.browse(cr,uid,record_ids):
                if (not line.invoiced) and (line.state not in ('draft','cancel')):
                    if not line.partner_id.id in invoices:
                        invoices[line.partner_id.id] = []
                    if line.product_id:
                        if line.product_id.product_tmpl_id.type == 'service':
                            a = line.product_id.property_account_expense.id
                            if not a:
                                a = line.product_id.categ_id.property_account_expense_categ.id    
                        else:
                            a = line.product_id.property_stock_account_input
                            if not a:
                                a = line.product_id.categ_id.property_stock_account_input_categ.id
                        if not a:
                            raise osv.except_osv(('Error!'),
                                    ('Define expense account for this product: "%s" (id:%d).') % \
                                            (line.product_id.name, line.product_id.id,))
                    else:
                        a = property_obj.get(cr, uid,
                                'property_account_expense_categ', 'product.category',
                                context=context).id
                    fpos = line.order_id.fiscal_position or False
                    a = account_fiscal_obj.map_account(cr, uid, fpos, a)
                    res = self.build_line(cr, uid, a, line, context=context)
                    inv_id = invoice_line_obj.create(cr, uid, res)
                    purchase_line_obj.write(cr, uid, [line.id], {'invoiced': True, 'invoice_lines': [(4, inv_id)]})
                    invoices[line.partner_id.id].append((line,inv_id))

            res = []
            for result in invoices.values():
                il = map(lambda x: x[1], result)
                orders = list(set(map(lambda x : x[0].order_id, result)))

                res.append(make_invoice_by_partner(orders[0].partner_id, orders, il))

        return {
            'domain': "[('id','in', ["+','.join(map(str,res))+"])]",
            'name': ('Supplier Invoices'),
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'account.invoice',
            'view_id': False,
            'context': "{'type':'in_invoice', 'journal_type': 'purchase'}",
            'type': 'ir.actions.act_window'
        }
purchase_line_invoice()
