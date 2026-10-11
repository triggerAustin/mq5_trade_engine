//+------------------------------------------------------------------+
//| MT5SymbolScan.mq5 - one-off SCRIPT (not an EA). Places no trades.|
//| Lists a CAPPED set of symbols (indices, metals, energy, bonds,   |
//| commodities) with folder, description, contract size, min lot    |
//| and (for a few) the first daily bar the server has.              |
//| Output: Common\Files\bridge\symbols.csv                          |
//+------------------------------------------------------------------+
#property script_show_inputs
#property copyright "mt5bot"
#property version   "2.00"

input string InpKeywords    = "index,indices,metal,energy,oil,brent,bond,commod,bund,treasury,crude,copper,silver,gold,equity,cash";
input int    InpMaxRows     = 300;   // maximum symbols written
input int    InpHistoryMax  = 40;    // maximum symbols whose D1 history start is checked (these get added to Market Watch)
input bool   InpLoadHistory = true;  // false = names only, fastest

string Clean(string s)
{
   StringReplace(s, ",", ";");
   StringReplace(s, "\"", "'");
   return s;
}

bool Matches(string text, const string &kw[])
{
   StringToLower(text);
   for(int k = 0; k < ArraySize(kw); k++)
      if(StringLen(kw[k]) > 0 && StringFind(text, kw[k]) >= 0)
         return true;
   return false;
}

void OnStart()
{
   string kw[];
   int nk = StringSplit(InpKeywords, ',', kw);
   for(int k = 0; k < nk; k++) { StringTrimLeft(kw[k]); StringTrimRight(kw[k]); StringToLower(kw[k]); }

   FolderCreate("bridge", FILE_COMMON);
   int h = FileOpen("bridge\\symbols.csv", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
   {
      PrintFormat("MT5SymbolScan: cannot open output (error %d)", GetLastError());
      return;
   }
   FileWriteString(h, "symbol,path,description,contract_size,volume_min,volume_step,digits,first_d1\n");
   int total = SymbolsTotal(false);
   PrintFormat("MT5SymbolScan: %d symbols on this server; keeping at most %d that match keywords", total, InpMaxRows);

   int rows = 0, hist = 0;
   for(int i = 0; i < total && rows < InpMaxRows; i++)
   {
      string s    = SymbolName(i, false);
      string path = SymbolInfoString(s, SYMBOL_PATH);
      string desc = SymbolInfoString(s, SYMBOL_DESCRIPTION);
      if(!Matches(path + " " + desc + " " + s, kw))
         continue;

      string first = "";
      if(InpLoadHistory && hist < InpHistoryMax)
      {
         hist++;
         SymbolSelect(s, true);
         datetime t[];
         int n = CopyTime(s, PERIOD_D1, D'1990.01.01', 1, t);
         long fd = 0;
         if(SeriesInfoInteger(s, PERIOD_D1, SERIES_SERVER_FIRSTDATE, fd) && fd > 0)
            first = TimeToString((datetime)fd, TIME_DATE);
         else if(n > 0)
            first = TimeToString(t[0], TIME_DATE);
      }
      string line = Clean(s) + "," + Clean(path) + "," + Clean(desc) + "," +
                    DoubleToString(SymbolInfoDouble(s, SYMBOL_TRADE_CONTRACT_SIZE), 4) + "," +
                    DoubleToString(SymbolInfoDouble(s, SYMBOL_VOLUME_MIN), 4) + "," +
                    DoubleToString(SymbolInfoDouble(s, SYMBOL_VOLUME_STEP), 4) + "," +
                    IntegerToString((long)SymbolInfoInteger(s, SYMBOL_DIGITS)) + "," + first + "\n";
      FileWriteString(h, line);
      rows++;
   }
   FileClose(h);
   PrintFormat("MT5SymbolScan: done. %d rows written (%d with history checked) to Common\\Files\\bridge\\symbols.csv", rows, hist);
}
