# get_token.py
from yoomoney import Authorize

CLIENT_ID = "68949D9F43102AFB0C9646C7EB203B5C459459E8551F010B48922A52D9A92968" # Оставь пустым, если используешь стандартный
CLIENT_SECRET = "08E4A9046A44D53B6D8E88714F9392726A0751A2A209AC4376B679847548EBB542FEE0629D875EE5BB59B091205F8421F6F08FAF52D44BFD381608CF83091DF3"
# Но лучше получить свой Client ID тут: https://yoomoney.ru/myservices/new

# Если лень регистрировать приложение, можно попробовать через стандартный flow библиотеки,
# но надежнее создать "Приложение" на сайте Юмани.
# 1. Иди на https://yoomoney.ru/myservices/new
# 2. Название: MyVPNBot
# 3. Redirect URI: https://google.com (любой сайт)
# 4. Скопируй Client ID, который выдадут.

print("Вставь Client ID ниже в коде и перезапусти скрипт, если еще не сделал этого.")

Authorize(
      client_id=CLIENT_ID,
      client_secret=CLIENT_SECRET,
      redirect_uri="https://google.com",
      scope=["account-info", "operation-history", "operation-details", "incoming-transfers", "payment-p2p"]
      )