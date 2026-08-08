import { AgGridReact } from "ag-grid-react";
import type { ColDef } from "ag-grid-community";
import { useMemo } from "react";

import "ag-grid-community/styles/ag-grid.css";
import "ag-grid-community/styles/ag-theme-quartz.css";

import { GRID_CLASS_NAME } from "../../components/grid/gridTheme";
import { useBooks, useCounterparties } from "../../hooks/useReferenceData";
import { useSelection } from "../../hooks/useSelection";
import type { Trade } from "../../hooks/useTrades";
import { useTrades } from "../../hooks/useTrades";
import { TradeActionsCell } from "./TradeActionsCell";
import { TradeEntryForm } from "./TradeEntryForm";

const columnDefs: ColDef<Trade>[] = [
  { field: "trade_date", headerName: "Trade date", width: 120 },
  { valueGetter: (p) => p.data?.counterparty.name, headerName: "Counterparty", flex: 1 },
  { valueGetter: (p) => p.data?.book.name, headerName: "Book", flex: 1 },
  { field: "commodity", headerName: "Commodity", width: 110 },
  { field: "trade_type", headerName: "Type", width: 100 },
  { field: "buy_sell", headerName: "B/S", width: 80 },
  { field: "volume", headerName: "Volume", width: 130, valueFormatter: (p) => Number(p.value).toLocaleString() },
  {
    field: "fixed_price",
    headerName: "Fixed price",
    width: 110,
    valueFormatter: (p) => (p.value == null ? "—" : `$${Number(p.value).toFixed(3)}`),
  },
  {
    field: "strike_price",
    headerName: "Strike",
    width: 110,
    valueFormatter: (p) => (p.value == null ? "—" : `$${Number(p.value).toFixed(3)} ${p.data?.option_type ?? ""}`),
  },
  {
    field: "power_block",
    headerName: "Block",
    width: 100,
    valueFormatter: (p) => p.value ?? "—",
  },
  {
    valueGetter: (p) =>
      p.data?.certificate_registry
        ? `${p.data.certificate_registry} (${p.data.vintage_year ?? "—"})`
        : null,
    headerName: "Registry (vintage)",
    width: 160,
    valueFormatter: (p) => p.value ?? "—",
  },
  { field: "delivery_start_month", headerName: "Delivery start", width: 130 },
  { field: "delivery_end_month", headerName: "Delivery end", width: 130 },
  { field: "status", headerName: "Status", width: 150 },
  { field: "version", headerName: "v", width: 60 },
  { headerName: "Actions", width: 180, cellRenderer: TradeActionsCell, sortable: false, filter: false },
];

export function TradeBlotterPage() {
  const { bookId } = useSelection();
  const { data: trades } = useTrades(bookId);
  const { data: counterparties } = useCounterparties();
  const { data: books } = useBooks();

  const rowData = useMemo(() => trades ?? [], [trades]);

  return (
    <div className="space-y-6">
      <TradeEntryForm counterparties={counterparties ?? []} books={books ?? []} />

      <div>
        <h2 className="text-sm uppercase tracking-wide text-slate-500 mb-2">
          Trade blotter {bookId ? "" : "(all books)"}
        </h2>
        <div className={GRID_CLASS_NAME} style={{ height: 420, width: "100%" }}>
          <AgGridReact<Trade> rowData={rowData} columnDefs={columnDefs} defaultColDef={{ sortable: true, resizable: true }} />
        </div>
      </div>
    </div>
  );
}
