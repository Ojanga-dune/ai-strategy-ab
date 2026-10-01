import unittest
from unittest.mock import MagicMock, patch
from core.exchange_connector import ExchangeConnector

class TestExchangeConnectorNormalization(unittest.TestCase):
    def setUp(self):
        self.connector = ExchangeConnector("mock_key", "mock_id", simulation_mode=True)

    def test_place_market_order_normalization(self):
        """
        Verify that place_market_order normalizes OANDA's response to include
        status='success' when orderCreateTransaction is present.
        """
        # Mock a real OANDA success response
        oanda_response = {
            'orderCreateTransaction': {'id': 'ord123'},
            'orderFillTransaction': {'id': 'fill123'}
        }

        with patch('requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = oanda_response

            # Set simulation_mode to False to hit the mock_post
            self.connector.simulation_mode = False

            res = self.connector.place_market_order("XAU_USD", 0.01)

            self.assertEqual(res.get('status'), 'success')
            self.assertEqual(res.get('orderCreateTransaction', {}).get('id'), 'ord123')

    def test_modify_order_normalization(self):
        """
        Verify that modify_order normalizes OANDA's response to include
        status='success' when orderCreateTransaction is present.
        """
        oanda_response = {
            'orderCreateTransaction': {'id': 'ord456'},
        }

        with patch('requests.post') as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = oanda_response

            self.connector.simulation_mode = False

            # Mock get_open_positions so it finds the trade
            self.connector.get_open_positions = MagicMock(return_value=[{
                'instrument': 'XAU_USD',
                'long': {'units': '1', 'tradeIDs': ['trd123']}
            }])

            res = self.connector.modify_order('trd123', stop_loss=2000.0)

            self.assertEqual(res.get('status'), 'success')
            self.assertEqual(res.get('orderCreateTransaction', {}).get('id'), 'ord456')

if __name__ == "__main__":
    unittest.main()
