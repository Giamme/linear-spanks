from service import invoice_total


def test_invoice_total():
    assert invoice_total(5, 3) == 15
