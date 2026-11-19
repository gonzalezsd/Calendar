import { Component } from '@angular/core';
import { FormsModule, NgForm } from '@angular/forms';
import { AppState } from '../core/app-state';

@Component({
  selector: 'app-login',
  imports: [FormsModule],
  templateUrl: './login.html'
})
export class LoginComponent {
  loginName = '';
  loginPassword = '';

  constructor(readonly state: AppState) {}

  async login(form: NgForm): Promise<void> {
    if (form.invalid) return;
    if (await this.state.login(this.loginName, this.loginPassword)) {
      this.loginPassword = '';
    }
  }
}
