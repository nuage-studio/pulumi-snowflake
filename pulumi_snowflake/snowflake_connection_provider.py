import snowflake.connector
from pulumi import Config

class SnowflakeConnectionProvider:
    """
    Returns a connection to a Snowflake database.
    """

    @staticmethod
    def create_from_config():
        """
        :return: A `SnowflakeConnectionProvider` instance which was created using credentials in the Pulumi config
        """
        config = Config()
        return SnowflakeConnectionProvider(
            config.require('snowflakeUsername'),
            config.require('snowflakePassword'),
            config.require('snowflakeAccountName')
        )

    def __init__(self, username, password, account_name):
        self.username = username
        self.password = password
        self.account_name = account_name

    def get(self):
        return snowflake.connector.connect(
            user=self.username,
            password=self.password,
            account=self.account_name
        )