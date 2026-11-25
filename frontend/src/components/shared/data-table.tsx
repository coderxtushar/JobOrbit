"use client";

import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useState } from "react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";

/**
 * TanStack Table with the Orbit look: sortable headers, optional row selection and a
 * clickable row. Sorting is client-side over the rows given; server paging stays with the
 * caller.
 */
export function DataTable<T>({
  columns,
  data,
  onRowClick,
  rowSelection,
  onRowSelectionChange,
  getRowId,
  empty,
  className,
}: {
  columns: ColumnDef<T, unknown>[];
  data: T[];
  onRowClick?: (row: T) => void;
  rowSelection?: RowSelectionState;
  onRowSelectionChange?: (state: RowSelectionState) => void;
  getRowId?: (row: T) => string;
  empty?: React.ReactNode;
  className?: string;
}) {
  const [sorting, setSorting] = useState<SortingState>([]);
  // TanStack Table returns fresh functions each render, so the React Compiler skips this
  // component on purpose; nothing here is passed into memoised children.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    state: { sorting, rowSelection: rowSelection ?? {} },
    onSortingChange: setSorting,
    onRowSelectionChange: (updater) => {
      if (!onRowSelectionChange) return;
      const next = typeof updater === "function" ? updater(rowSelection ?? {}) : updater;
      onRowSelectionChange(next);
    },
    enableRowSelection: Boolean(onRowSelectionChange),
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  return (
    <div className={cn("orbit-card overflow-hidden", className)}>
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id} className="border-line hover:bg-transparent">
              {group.headers.map((header) => {
                const sortable = header.column.getCanSort();
                const sorted = header.column.getIsSorted();
                return (
                  <TableHead
                    key={header.id}
                    className="h-9 bg-surface-2/50 text-[11px] font-semibold uppercase tracking-wider text-text-3"
                  >
                    {header.isPlaceholder ? null : sortable ? (
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 hover:text-text-1"
                        onClick={header.column.getToggleSortingHandler()}
                      >
                        {flexRender(header.column.columnDef.header, header.getContext())}
                        {sorted === "asc" ? <ArrowUp className="size-3" /> : null}
                        {sorted === "desc" ? <ArrowDown className="size-3" /> : null}
                      </button>
                    ) : (
                      flexRender(header.column.columnDef.header, header.getContext())
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={columns.length} className="p-0">
                {empty ?? <p className="py-10 text-center text-sm text-text-3">Nothing to show.</p>}
              </TableCell>
            </TableRow>
          ) : (
            table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                data-state={row.getIsSelected() ? "selected" : undefined}
                onClick={onRowClick ? () => onRowClick(row.original) : undefined}
                className={cn(
                  "border-line transition-colors data-[state=selected]:bg-violet-soft",
                  onRowClick && "cursor-pointer hover:bg-surface-2/60",
                )}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} className="py-2.5 text-sm text-text-1">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </div>
  );
}
