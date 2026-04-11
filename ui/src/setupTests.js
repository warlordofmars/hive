// Copyright (c) 2026 John Carter. All rights reserved.
import "@testing-library/jest-dom";

// jsdom does not implement scrollIntoView; stub it so components that call it
// do not throw and coverage branches are reachable.
globalThis.HTMLElement.prototype.scrollIntoView = function () {};
