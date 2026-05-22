# other/stellar/constants.py
"""Stellar network constants: addresses, assets, configuration."""

from stellar_sdk import Asset
from shared.domain.stellar_addresses import MTLAddresses

# Base transaction fee
BASE_FEE = 10001

# Records per batch for operations
PACK_COUNT = 70


class MTLAssets:
    """Asset definitions for MTL ecosystem."""

    mtl_asset = Asset("MTL", MTLAddresses.public_issuer)
    mtlrect_asset = Asset("MTLRECT", MTLAddresses.public_issuer)
    eurmtl_asset = Asset("EURMTL", MTLAddresses.public_issuer)
    eurdebt_asset = Asset("EURDEBT", MTLAddresses.public_issuer)
    xlm_asset = Asset("XLM", None)
    satsmtl_asset = Asset("SATSMTL", MTLAddresses.public_issuer)
    btcmtl_asset = Asset("BTCMTL", MTLAddresses.public_issuer)
    btcdebt_asset = Asset("BTCDEBT", MTLAddresses.public_issuer)
    usdc_asset = Asset("USDC", "GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN")
    yusdc_asset = Asset("yUSDC", "GDGTVWSM4MGS4T7Z6W4RPWOCHE2I6RDFCIFZGS3DOA63LWQTRNZNTTFF")
    btc_asset = Asset("BTC", "GDPJALI4AZKUU2W426U5WKMAT6CN3AJRPIIRYR2YM54TL2GDWO5O2MZM")
    ybtc_asset = Asset("yBTC", "GBUVRNH4RW4VLHP4C5MOF46RRIRZLAVHYGX45MVSTKA2F6TMR7E7L6NW")
    mrxpinvest_asset = Asset("MrxpInvest", "GDAJVYFMWNIKYM42M6NG3BLNYXC3GE3WMEZJWTSYH64JLZGWVJPTGGB7")
    mtlfarm_asset = Asset("MTLFARM", MTLAddresses.public_farm)
    usd_farm_asset = Asset("USDFARM", MTLAddresses.public_farm)
    usdmm_asset = Asset("USDMM", MTLAddresses.public_usdm)
    usdm_asset = Asset("USDM", MTLAddresses.public_usdm)
    damircoin_asset = Asset("DamirCoin", MTLAddresses.public_damir)
    agora_asset = Asset("Agora", "GBGGX7QD3JCPFKOJTLBRAFU3SIME3WSNDXETWI63EDCORLBB6HIP2CRR")
    toc_asset = Asset("TOC", "GBJ3HT6EDPWOUS3CUSIJW5A4M7ASIKNW4WFTLG76AAT5IE6VGVN47TIC")
    aqua_asset = Asset("AQUA", "GBNZILSTVQZ4R7IKQDGHYGY2QXL5QOFJYQMXPKWRRM5PAV7Y4M67AQUA")
    mtlap_asset = Asset("MTLAP", "GCNVDZIHGX473FEI7IXCUAEXUJ4BGCKEMHF36VYP5EMS7PX2QBLAMTLA")
    eurc_asset = Asset("EURC", "GAQRF3UGHBT6JYQZ7YSUYCIYWAF4T2SAA5237Q5LIQYJOHHFAWDXZ7NM")
    labr_asset = Asset("LABR", "GA7I6SGUHQ26ARNCD376WXV5WSE7VJRX6OEFNFCEGRLFGZWQIV73LABR")


# Exchange bot addresses (currently disabled)
EXCHANGE_BOTS: tuple = ()
