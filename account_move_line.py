from openerp.osv import fields, osv

class account_move_line(osv.osv):
    
    _inherit = "account.move.line"
    _columns = {
        'stock_move_id': fields.many2one('stock.move',string= 'Stock Move'),
    }