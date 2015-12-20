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

from openerp.osv import fields, osv

class AccountAngloSaxonCompany(osv.osv):
    _inherit = 'res.company'
    
    _columns = {
                'price_variance_writeoff_amount': fields.float('Price Variance Write-Off Amount', digits=(18,2), required = True,),
                'price_variance_writeoff_account': fields.many2one('account.account', string="Price Variance Write-Off Account"),
                'stock_input_account': fields.many2one('account.account', string="Stock Input (Supplier) Account "),
                'stock_output_account': fields.many2one('account.account', string="Stock Output (Customer) Account"),
                }
    
AccountAngloSaxonCompany()
