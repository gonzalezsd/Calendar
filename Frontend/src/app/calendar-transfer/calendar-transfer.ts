import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AppState } from '../core/app-state';

type ImportResult = { asignaciones: number; tipados: number; notas: number; recordatorios: number } &
  ({ year: number } | { years: number[] });

@Component({
  selector: 'app-calendar-transfer',
  imports: [FormsModule],
  templateUrl: './calendar-transfer.html'
})
export class CalendarTransferComponent implements OnInit {
  exportYear: number | 'all' | null = null;
  file: File | null = null;
  @ViewChild('csvFile') private fileInput?: ElementRef<HTMLInputElement>;

  constructor(readonly state: AppState) {}

  ngOnInit(): void {
    this.exportYear = this.state.year;
  }

  resetForm(): void {
    this.file = null;
    if (this.fileInput) this.fileInput.nativeElement.value = '';
    this.exportYear = this.state.year;
  }

  selectFile(event: Event): void {
    const input = event.target;
    if (input instanceof HTMLInputElement) this.file = input.files?.item(0) ?? null;
  }

  async exportCalendar(): Promise<void> {
    const year = this.exportYear;
    if (year === null || (year !== 'all' && !this.state.years.includes(year)) || !this.state.years.length) return;
    await this.state.run(async () => {
      const csv = await this.state.requestCsv(year === 'all' ? '/api/calendario/exportar' : `/api/calendario/${year}/exportar`);
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
      try {
        const link = document.createElement('a');
        link.href = url;
        link.download = year === 'all' ? 'calendario-completo.csv' : `calendario-${year}.csv`;
        link.click();
      } finally {
        URL.revokeObjectURL(url);
      }
      this.state.message = 'Calendario exportado.';
    });
  }

  async importCalendar(): Promise<void> {
    const file = this.file;
    if (!file) return;
    await this.state.run(async () => {
      const result = await this.state.request<ImportResult>('POST', '/api/calendario/importar', file);
      this.file = null;
      if (this.fileInput) this.fileInput.nativeElement.value = '';
      const label = 'year' in result ? `Calendario ${result.year}` : 'Calendario completo';
      this.state.message = `${label} importado: ${result.asignaciones} asignaciones, ${result.tipados} tipados, ${result.notas} notas y ${result.recordatorios} recordatorios.`;
      try {
        await this.state.loadYears('year' in result ? result.year : undefined);
      } catch (error) {
        this.state.message += ' No se pudo actualizar el calendario; vuelve a cargarlo.';
        throw error;
      }
    });
  }
}
