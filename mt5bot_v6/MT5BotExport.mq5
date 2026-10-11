//+------------------------------------------------------------------+
//| MT5BotExport.mq5  -  Phase 1: EXPORT ONLY. This EA places NO     |
//| trades and modifies nothing. It writes files that the Python     |
//| side (bridge_sync.py) reads:                                     |
//|   <Common\Files>\bridge\bars\<MARKET>_D1.csv  completed D1 bars  |
//|   <Common\Files>\bridge\specs.json            symbol specs       |
//|   <Common\Files>\bridge\account.json          account state      |
//|   <Common\Files>\bridge\heartbeat.json        liveness           |
//| Files are written to a .tmp name and renamed, so a reader never  |
//| sees a half-written file.                                        |
//+------------------------------------------------------------------+
#property copyright "mt5bot"
#property version   "1.00"
#property strict

input string InpMarkets  = "EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,NZDUSD,XAUUSD"; // canonical names
input string InpSuffix   = "";        // broker suffix appended to each name, e.g. ".m" (leave empty if none)
input int    InpBars     = 400;       // completed daily bars to export per market
input int    InpEverySec = 60;        // export interval
input string InpDir      = "bridge";  // folder inside the Common\Files folder

string g_canon[];

//--- helpers -----------------------------------------------------------
string Num(const double v, const int digits = 8) { return DoubleToString(v, digits); }

string JStr(string s)
{
   StringReplace(s, "\\", "\\\\");
   StringReplace(s, "\"", "\\\"");
   return "\"" + s + "\"";
}

string IsoNow(const datetime t)
{
   MqlDateTime d;
   TimeToStruct(t, d);
   return StringFormat("%04d-%02d-%02dT%02d:%02d:%02d", d.year, d.mon, d.day, d.hour, d.min, d.sec);
}

bool WriteTextAtomic(const string relpath, const string text)
{
   string tmp = relpath + ".tmp";
   int h = FileOpen(tmp, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
   {
      PrintFormat("MT5BotExport: cannot open %s (error %d)", tmp, GetLastError());
      return false;
   }
   FileWriteString(h, text);
   FileClose(h);
   if(!FileMove(tmp, FILE_COMMON, relpath, FILE_COMMON | FILE_REWRITE))
   {
      PrintFormat("MT5BotExport: cannot rename %s to %s (error %d)", tmp, relpath, GetLastError());
      FileDelete(tmp, FILE_COMMON);
      return false;
   }
   return true;
}

//--- exports -----------------------------------------------------------
bool ExportBars(const string canon, const string broker)
{
   MqlRates r[];
   ArraySetAsSeries(r, false);                      // oldest first
   int got = CopyRates(broker, PERIOD_D1, 1, InpBars, r);   // start position 1 = skip the still-forming bar
   if(got <= 0)
   {
      PrintFormat("MT5BotExport: no D1 bars yet for %s (error %d) - will retry", broker, GetLastError());
      return false;
   }
   int dg = (int)SymbolInfoInteger(broker, SYMBOL_DIGITS);
   string s = "date,open,high,low,close,tickvol,spread\n";
   for(int i = 0; i < got; i++)
   {
      s += TimeToString(r[i].time, TIME_DATE) + "," + DoubleToString(r[i].open, dg) + "," +
           DoubleToString(r[i].high, dg) + "," + DoubleToString(r[i].low, dg) + "," +
           DoubleToString(r[i].close, dg) + "," + IntegerToString((long)r[i].tick_volume) + "," +
           IntegerToString(r[i].spread) + "\n";
   }
   return WriteTextAtomic(InpDir + "\\bars\\" + canon + "_D1.csv", s);
}

string SymbolSpecJson(const string canon, const string broker)
{
   string s = "\"" + canon + "\":{";
   s += "\"broker_symbol\":" + JStr(broker);
   s += ",\"digits\":" + IntegerToString((long)SymbolInfoInteger(broker, SYMBOL_DIGITS));
   s += ",\"contract_size\":" + Num(SymbolInfoDouble(broker, SYMBOL_TRADE_CONTRACT_SIZE));
   s += ",\"tick_size\":" + Num(SymbolInfoDouble(broker, SYMBOL_TRADE_TICK_SIZE));
   s += ",\"tick_value\":" + Num(SymbolInfoDouble(broker, SYMBOL_TRADE_TICK_VALUE));
   s += ",\"volume_min\":" + Num(SymbolInfoDouble(broker, SYMBOL_VOLUME_MIN));
   s += ",\"volume_max\":" + Num(SymbolInfoDouble(broker, SYMBOL_VOLUME_MAX));
   s += ",\"volume_step\":" + Num(SymbolInfoDouble(broker, SYMBOL_VOLUME_STEP));
   s += ",\"stops_level\":" + IntegerToString((long)SymbolInfoInteger(broker, SYMBOL_TRADE_STOPS_LEVEL));
   s += ",\"freeze_level\":" + IntegerToString((long)SymbolInfoInteger(broker, SYMBOL_TRADE_FREEZE_LEVEL));
   s += ",\"spread_points\":" + IntegerToString((long)SymbolInfoInteger(broker, SYMBOL_SPREAD));
   s += ",\"trade_mode\":" + IntegerToString((long)SymbolInfoInteger(broker, SYMBOL_TRADE_MODE));
   s += ",\"filling_flags\":" + IntegerToString((long)SymbolInfoInteger(broker, SYMBOL_FILLING_MODE));
   s += ",\"swap_long\":" + Num(SymbolInfoDouble(broker, SYMBOL_SWAP_LONG));
   s += ",\"swap_short\":" + Num(SymbolInfoDouble(broker, SYMBOL_SWAP_SHORT));
   s += ",\"currency_base\":" + JStr(SymbolInfoString(broker, SYMBOL_CURRENCY_BASE));
   s += ",\"currency_profit\":" + JStr(SymbolInfoString(broker, SYMBOL_CURRENCY_PROFIT));
   s += "}";
   return s;
}

void ExportAll()
{
   string specs = "{\"symbols\":{";
   int ok_bars = 0;
   for(int i = 0; i < ArraySize(g_canon); i++)
   {
      string canon  = g_canon[i];
      string broker = canon + InpSuffix;
      if(!SymbolSelect(broker, true))
      {
         PrintFormat("MT5BotExport: symbol %s not found at this broker (suffix '%s'?)", broker, InpSuffix);
         continue;
      }
      if(ExportBars(canon, broker)) ok_bars++;
      if(i > 0 && StringLen(specs) > 14) specs += ",";
      specs += SymbolSpecJson(canon, broker);
   }
   specs += "}}\n";
   WriteTextAtomic(InpDir + "\\specs.json", specs);

   //--- account
   long   tm = AccountInfoInteger(ACCOUNT_TRADE_MODE);     // 0 demo, 1 contest, 2 real
   long   mm = AccountInfoInteger(ACCOUNT_MARGIN_MODE);    // 0 retail netting, 1 exchange, 2 retail hedging
   string tms = (tm == ACCOUNT_TRADE_MODE_DEMO ? "demo" : (tm == ACCOUNT_TRADE_MODE_CONTEST ? "contest" : "real"));
   string mms = (mm == ACCOUNT_MARGIN_MODE_RETAIL_HEDGING ? "hedging" : (mm == ACCOUNT_MARGIN_MODE_RETAIL_NETTING ? "netting" : "exchange"));
   string acc = "{";
   acc += "\"login\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   acc += ",\"server\":" + JStr(AccountInfoString(ACCOUNT_SERVER));
   acc += ",\"company\":" + JStr(AccountInfoString(ACCOUNT_COMPANY));
   acc += ",\"currency\":" + JStr(AccountInfoString(ACCOUNT_CURRENCY));
   acc += ",\"trade_mode\":" + IntegerToString(tm) + ",\"trade_mode_text\":" + JStr(tms);
   acc += ",\"margin_mode\":" + IntegerToString(mm) + ",\"margin_mode_text\":" + JStr(mms);
   acc += ",\"leverage\":" + IntegerToString(AccountInfoInteger(ACCOUNT_LEVERAGE));
   acc += ",\"balance\":" + Num(AccountInfoDouble(ACCOUNT_BALANCE), 2);
   acc += ",\"equity\":" + Num(AccountInfoDouble(ACCOUNT_EQUITY), 2);
   acc += ",\"margin\":" + Num(AccountInfoDouble(ACCOUNT_MARGIN), 2);
   acc += "}\n";
   WriteTextAtomic(InpDir + "\\account.json", acc);

   //--- heartbeat LAST, so a fresh heartbeat means the files above are fresh too
   string hb = "{";
   hb += "\"utc\":" + JStr(IsoNow(TimeGMT()));
   hb += ",\"server_time\":" + JStr(IsoNow(TimeTradeServer()));
   hb += ",\"connected\":" + IntegerToString(TerminalInfoInteger(TERMINAL_CONNECTED));
   hb += ",\"trade_allowed\":" + IntegerToString(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED));
   hb += ",\"build\":" + IntegerToString(TerminalInfoInteger(TERMINAL_BUILD));
   hb += ",\"markets_exported\":" + IntegerToString(ok_bars);
   hb += ",\"ea_version\":\"1.00-export-only\"}\n";
   WriteTextAtomic(InpDir + "\\heartbeat.json", hb);
}

//--- events ------------------------------------------------------------
int OnInit()
{
   int n = StringSplit(InpMarkets, ',', g_canon);
   if(n <= 0)
   {
      Print("MT5BotExport: InpMarkets is empty");
      return INIT_PARAMETERS_INCORRECT;
   }
   for(int i = 0; i < n; i++)
   {
      StringTrimLeft(g_canon[i]);
      StringTrimRight(g_canon[i]);
   }
   FolderCreate(InpDir, FILE_COMMON);
   FolderCreate(InpDir + "\\bars", FILE_COMMON);
   EventSetTimer(MathMax(10, InpEverySec));
   ExportAll();
   PrintFormat("MT5BotExport started (EXPORT ONLY, no trading). Files go to Common\\Files\\%s", InpDir);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) { EventKillTimer(); }
void OnTimer()                  { ExportAll(); }
void OnTick()                   { }
