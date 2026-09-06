import test from "node:test";
import assert from "node:assert/strict";
import {MOCK_CATALOG,getProduct,searchCatalog} from "../lib/catalog";

test("mock catalog has bangles and watches",()=>{assert.ok(MOCK_CATALOG.some(p=>p.category==="bangles"));assert.ok(MOCK_CATALOG.some(p=>p.category==="watches"));});
test("search excludes already shown SKUs",()=>{const first=searchCatalog("bangles",[],3);assert.equal(first.length,3);const next=searchCatalog("bangles",first.map(p=>p.id),3);assert.ok(next.every(p=>!first.some(x=>x.id===p.id)));});
test("product lookup returns cart product",()=>{assert.equal(getProduct("BNG-101")?.id,"BNG-101");assert.equal(getProduct("BAD"),null);});
