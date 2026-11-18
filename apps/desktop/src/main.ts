import { mount } from 'svelte';
import App from './App.svelte';
import './style.css';
import './refresh.css';
import './capri-theme.css';

mount(App, { target: document.getElementById('app')! });
