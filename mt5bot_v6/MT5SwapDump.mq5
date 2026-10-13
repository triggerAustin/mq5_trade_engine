//+------------------------------------------------------------------+
//| MT5SwapDump.mq5 - one-off SCRIPT. Places NO trades.              |
//| Writes the broker's real overnight swap / spread / contract data |
//| for each symbol to Common\Files\bridge\swaps.csv                 |
//+------------------------------------------------------------------+
#property script_show_inputs
#property version   "1.00"
input string InpSymbols = "EURUSD,GBPUSD,USDJPY,AUDUSD,USDCAD,USDCHF,NZDUSD,XAUUSD,XAGUSD,US500,US30,USTEC,DE40,UK100,JP225,TLT,IEF,LQD,SPY,EFA,EEM,GLD,DBC,USO,USOIL,UKOIL";

void OnStart()
{
   FolderCreate("bridge", FILE_COMMON);
   string names[];
   int n = StringSplit(InpSymbols, ',', names);
   int h = FileOpen("bridge\\swaps.csv", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE) { PrintFormat("MT5SwapDump: cannot open output (error %d)", GetLastError()); return; }
   FileWriteString(h, "symbol,found,swap_mode,swap_long,swap_short,swap_rollover3days,contract_size,digits,point,bid,ask,spread_pts,calc_mode,vol_min,tick_value,tick_size,currency_profit\n");
   PrintFormat("MT5SwapDump: %d symbols to read", n);
   int found = 0;
   for(int i = 0; i < n; i++)
   {
      string s = names[i];
      StringTrimLeft(s); StringTrimRight(s);
      if(StringLen(s) == 0) continue;
      if(!SymbolSelect(s, true)) { PrintFormat("MT5SwapDump: [%d/%d] %s not on this server", i + 1, n, s); FileWriteString(h, s + ",0\n"); continue; }
      Sleep(300);
      MqlTick t; SymbolInfoTick(s, t);
      string line = StringFormat("%s,1,%d,%.6f,%.6f,%d,%.4f,%d,%.8f,%.8f,%.8f,%d,%d,%.4f,%.6f,%.8f,%s",
         s, (int)SymbolInfoInteger(s, SYMBOL_SWAP_MODE),
         SymbolInfoDouble(s, SYMBOL_SWAP_LONG), SymbolInfoDouble(s, SYMBOL_SWAP_SHORT),
         (int)SymbolInfoInteger(s, SYMBOL_SWAP_ROLLOVER3DAYS),
         SymbolInfoDouble(s, SYMBOL_TRADE_CONTRACT_SIZE), (int)SymbolInfoInteger(s, SYMBOL_DIGITS),
         SymbolInfoDouble(s, SYMBOL_POINT), t.bid, t.ask, (int)SymbolInfoInteger(s, SYMBOL_SPREAD),
         (int)SymbolInfoInteger(s, SYMBOL_TRADE_CALC_MODE), SymbolInfoDouble(s, SYMBOL_VOLUME_MIN),
         SymbolInfoDouble(s, SYMBOL_TRADE_TICK_VALUE), SymbolInfoDouble(s, SYMBOL_TRADE_TICK_SIZE),
         SymbolInfoString(s, SYMBOL_CURRENCY_PROFIT));
      FileWriteString(h, line + "\n");
      found++;
      PrintFormat("MT5SwapDump: [%d/%d] %s swap long %.4f short %.4f", i + 1, n, s, SymbolInfoDouble(s, SYMBOL_SWAP_LONG), SymbolInfoDouble(s, SYMBOL_SWAP_SHORT));
   }
   FileClose(h);
   PrintFormat("MT5SwapDump: DONE - %d of %d found. File: Common\\Files\\bridge\\swaps.csv", found, n);
}
