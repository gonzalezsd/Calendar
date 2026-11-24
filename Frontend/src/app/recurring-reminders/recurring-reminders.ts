import { Component, OnInit } from '@angular/core';
import { FormsModule, NgForm } from '@angular/forms';
import { AppState } from '../core/app-state';
import { RecurringReminder } from '../core/models';

@Component({
  selector: 'app-recurring-reminders',
  imports: [FormsModule],
  templateUrl: './recurring-reminders.html'
})
export class RecurringRemindersComponent implements OnInit {
  reminders: RecurringReminder[] = [];
  loaded = false;
  editingId: number | null = null;
  reminderForm: { dia: number | null; mes: number | null; hora: string; texto: string; repetir: boolean } =
    { dia: 1, mes: 1, hora: '', texto: '', repetir: true };

  constructor(readonly state: AppState) {}

  async ngOnInit(): Promise<void> {
    this.loaded = false;
    await this.state.run(async () => {
      this.reminders = await this.state.request<RecurringReminder[]>('GET', '/api/recordatorios/recurrentes');
      this.loaded = true;
    });
  }

  editReminder(reminder: RecurringReminder): void {
    this.editingId = reminder.recordatorio_id;
    this.reminderForm = { dia: reminder.dia, mes: reminder.mes, hora: reminder.hora ?? '', texto: reminder.texto, repetir: reminder.repetir };
  }

  resetForm(): void {
    this.editingId = null;
    this.reminderForm = { dia: 1, mes: 1, hora: '', texto: '', repetir: true };
  }

  get validDate(): boolean {
    const { dia, mes } = this.reminderForm;
    if (dia === null || mes === null || !Number.isInteger(dia) || !Number.isInteger(mes) || mes < 1 || mes > 12 || dia < 1) return false;
    const date = new Date(Date.UTC(2000, mes - 1, dia));
    return date.getUTCMonth() === mes - 1 && date.getUTCDate() === dia;
  }

  async saveReminder(form: NgForm): Promise<void> {
    if (form.invalid || !this.validDate || !this.reminderForm.texto.trim() || this.editingId === null) return;
    await this.state.run(async () => {
      const { dia, mes, hora, texto, repetir } = this.reminderForm;
      await this.state.request('PATCH', `/api/recordatorios/${this.editingId}`, { dia, mes, hora: hora || null, texto, repetir });
      this.resetForm();
      this.reminders = await this.state.request<RecurringReminder[]>('GET', '/api/recordatorios/recurrentes');
      if (this.state.year !== null) await this.state.loadCalendar(this.state.year);
      this.state.message = 'Recordatorio actualizado.';
    });
  }
}
