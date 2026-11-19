import { Component } from '@angular/core';
import { FormsModule, NgForm } from '@angular/forms';
import { AppState } from '../core/app-state';

@Component({
  selector: 'app-calendar',
  imports: [FormsModule],
  templateUrl: './calendar.html'
})
export class CalendarComponent {
  readonly weekdays = ['L', 'M', 'X', 'J', 'V', 'S', 'D'];
  newYear = new Date().getFullYear();

  constructor(readonly state: AppState) {}

  async createYear(form: NgForm): Promise<void> {
    if (form.invalid || !Number.isInteger(this.newYear)) return;
    await this.state.run(async () => {
      await this.state.request('POST', '/api/new_year', { year: this.newYear });
      await this.state.loadYears(this.newYear);
      this.state.view = 'calendar';
      this.state.message = 'Año creado.';
    });
  }
}
