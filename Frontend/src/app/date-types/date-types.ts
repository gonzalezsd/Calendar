import { Component, OnInit } from '@angular/core';
import { FormsModule, NgForm } from '@angular/forms';
import { AppState } from '../core/app-state';
import { DateType, EditableType } from '../core/models';

@Component({
  selector: 'app-date-types',
  imports: [FormsModule],
  templateUrl: './date-types.html'
})
export class DateTypesComponent implements OnInit {
  dateTypes: DateType[] = [];
  editingId: number | null = null;
  typeForm: EditableType = this.emptyType();

  constructor(readonly state: AppState) {}

  async ngOnInit(): Promise<void> {
    const target = this.state.editTarget?.view === 'tipos' ? this.state.editTarget.id : null;
    this.state.editTarget = null;
    await this.state.run(async () => {
      this.dateTypes = await this.state.request<DateType[]>('GET', '/api/tipos-fecha');
      const type = this.dateTypes.find(item => item.tipo_id === target);
      if (type) this.editType(type);
      else if (target !== null) this.state.error = 'El tipo de fecha ya no está disponible.';
    });
  }

  editType(type: DateType): void {
    this.editingId = type.tipo_id;
    this.typeForm = { ...type };
  }

  resetForm(): void {
    this.editingId = null;
    this.typeForm = this.emptyType();
  }

  private emptyType(): EditableType {
    return { nombre: '', descripcion: '', color: '#ef4444', en_borde: false, activo: false };
  }

  async saveType(form: NgForm): Promise<void> {
    if (form.invalid) return;
    await this.state.run(async () => {
      const { nombre, descripcion, color, en_borde, activo } = this.typeForm;
      const current = this.dateTypes.find(type => type.tipo_id === this.editingId);
      const payload: Record<string, unknown> = { nombre, descripcion, color, activo };
      if (!current || en_borde !== current.en_borde) payload['en_borde'] = en_borde;
      const url = this.editingId === null ? '/api/tipos-fecha' : `/api/tipos-fecha/${this.editingId}`;
      await this.state.request(this.editingId === null ? 'POST' : 'PATCH', url, payload);
      this.resetForm();
      this.dateTypes = await this.state.request<DateType[]>('GET', '/api/tipos-fecha');
      if (this.state.year !== null) await this.state.loadCalendar(this.state.year);
      this.state.message = 'Tipo de fecha guardado.';
    });
  }
}
