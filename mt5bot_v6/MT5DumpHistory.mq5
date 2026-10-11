//+------------------------------------------------------------------+
//| MT5DumpHistory.mq5 - one-off SCRIPT. Places NO trades.           |
//| For each symbol in InpSymbols: downloads the full DAILY history  |
//| from the server (bounded wait) and writes                        |
//|   Common\Files\bridge\hist\<SYMBOL>_D1.csv                       |
//|   (date,open,high,low,close,tickvol,spread)  date = YYYY-MM-DD   |
//| and a summary  Common\Files\bridge\hist\_summary.csv             |
//| Progress for every symbol is printed to the Experts tab.         |
//+------------------------------------------------------------------+
#property script_show_inputs
#property copyright "mt5bot"
#property version   "1.00"

input string InpSymbols = "XAUUSD,XAGUSD,XPTUSD,XPDUSD,TLT,IEF,DBC,USO,US500,US30,DE40,SPY,QQQ,IWM,EFA,EEM,EWJ,VGK,GLD,SLV,LQD,HYG,TIP,SHY,UNG,VNQ,AGG,XLE";
input int    InpWaitSec = 90;     // max seconds to wait for each symbol's history
input string InpOutDir  = "bridge\\hist";

string D(const datetime t)
{
   MqlDateTime m;
   TimeToStruct(t, m);
   return StringFormat("%04d-%02d-%02d", m.year, m.mon, m.day);
}

void OnStart()
{
   FolderCreate("bridge", FILE_COMMON);
   FolderCreate(InpOutDir, FILE_COMMON);

   string names[];
   int n = StringSplit(InpSymbols, ',', names);
   int hs = FileOpen(InpOutDir + "\\_summary.csv", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(hs == INVALID_HANDLE) { PrintFormat("MT5DumpHistory: cannot open summary (error %d)", GetLastError()); return; }
   FileWriteString(hs, "symbol,status,server_first,got_first,got_last,bars,seconds\n");
   FileFlush(hs);
   PrintFormat("MT5DumpHistory: %d symbols to fetch, max %d s each", n, InpWaitSec);

   int okc = 0;
   for(int i = 0; i < n; i++)
   {
      string s = names[i];
      StringTrimLeft(s); StringTrimRight(s);
      if(StringLen(s) == 0) continue;
      uint t0 = GetTickCount();
      PrintFormat("MT5DumpHistory: [%d/%d] %s - starting", i + 1, n, s);

      if(!SymbolSelect(s, true))
      {
         PrintFormat("MT5DumpHistory: [%d/%d] %s NOT FOUND on this server", i + 1, n, s);
         FileWriteString(hs, s + ",not_found,,,,0,0\n"); FileFlush(hs);
         continue;
      }

      // wait (bounded) for the server to tell us its first bar
      long sfd = 0;
      while((GetTickCount() - t0) < (uint)(InpWaitSec * 1000))
      {
         if(SeriesInfoInteger(s, PERIOD_D1, SERIES_SERVER_FIRSTDATE, sfd) && sfd > 0) break;
         Bars(s, PERIOD_D1);          // nudges the terminal to start syncing
         Sleep(500);
      }
      if(sfd <= 0)
      {
         PrintFormat("MT5DumpHistory: [%d/%d] %s no server first date within %d s - skipped", i + 1, n, s, InpWaitSec);
         FileWriteString(hs, s + ",no_server_date,,,,0," + IntegerToString((int)((GetTickCount() - t0) / 1000)) + "\n"); FileFlush(hs);
         continue;
      }

      // request the whole range until we reach the server's first bar (bounded)
      MqlRates r[];
      ArraySetAsSeries(r, false);
      int got = 0;
      int attempt = 0;
      while((GetTickCount() - t0) < (uint)(InpWaitSec * 1000))
      {
         attempt++;
         got = CopyRates(s, PERIOD_D1, (datetime)sfd, TimeCurrent(), r);
         if(got > 0 && r[0].time <= (datetime)sfd + 10 * 86400) break;
         if(attempt % 5 == 0)
            PrintFormat("MT5DumpHistory: [%d/%d] %s still loading... have %d bars (%d s)", i + 1, n, s, got > 0 ? got : 0, (int)((GetTickCount() - t0) / 1000));
         Sleep(1000);
      }
      if(got <= 0)
      {
         PrintFormat("MT5DumpHistory: [%d/%d] %s no bars returned (error %d)", i + 1, n, s, GetLastError());
         FileWriteString(hs, s + ",no_bars," + D((datetime)sfd) + ",,,0," + IntegerToString((int)((GetTickCount() - t0) / 1000)) + "\n"); FileFlush(hs);
         continue;
      }

      int dg = (int)SymbolInfoInteger(s, SYMBOL_DIGITS);
      int h = FileOpen(InpOutDir + "\\" + s + "_D1.csv", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
      if(h == INVALID_HANDLE)
      {
         PrintFormat("MT5DumpHistory: [%d/%d] %s cannot open output (error %d)", i + 1, n, s, GetLastError());
         continue;
      }
      FileWriteString(h, "date,open,high,low,close,tickvol,spread\n");
      for(int k = 0; k < got; k++)
         FileWriteString(h, D(r[k].time) + "," + DoubleToString(r[k].open, dg) + "," + DoubleToString(r[k].high, dg) + "," +
                         DoubleToString(r[k].low, dg) + "," + DoubleToString(r[k].close, dg) + "," +
                         IntegerToString((long)r[k].tick_volume) + "," + IntegerToString(r[k].spread) + "\n");
      FileClose(h);

      bool complete = (r[0].time <= (datetime)sfd + 10 * 86400);
      int secs = (int)((GetTickCount() - t0) / 1000);
      PrintFormat("MT5DumpHistory: [%d/%d] %s %s - %d bars %s -> %s (server starts %s) in %d s", i + 1, n, s,
                  complete ? "OK" : "PARTIAL", got, D(r[0].time), D(r[got - 1].time), D((datetime)sfd), secs);
      FileWriteString(hs, s + "," + (complete ? "ok" : "partial") + "," + D((datetime)sfd) + "," + D(r[0].time) + "," +
                      D(r[got - 1].time) + "," + IntegerToString(got) + "," + IntegerToString(secs) + "\n");
      FileFlush(hs);
      if(complete) okc++;
   }
   FileClose(hs);
   PrintFormat("MT5DumpHistory: ALL DONE - %d of %d symbols complete. Files in Common\\Files\\%s", okc, n, InpOutDir);
}
