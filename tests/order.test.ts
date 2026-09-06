import assert from "node:assert/strict";
import test from "node:test";
import {cartTotal,remainingAfterAdvance,validCustomer,whatsappOrderUrl} from "../lib/order";

const cart=[{productId:"BNG-101",qty:2,name:"Kashmiri Gold Bangles",image:"https://example.com/a.jpg",price:1499,size:"2.6",color:"Gold"},{productId:"WAT-201",qty:1,name:"Classic Black Watch",image:"https://example.com/b.jpg",price:2499,size:"Adjustable",color:"Black"}];
const customer={fullName:"Ali Raza",phone:"03231234567",city:"Lahore",address:"House 1, Street 2, Lahore",notes:"Call first"};

test("calculates order total and Rs 300 remaining",()=>{const total=cartTotal(cart);assert.equal(total,5497);assert.equal(remainingAfterAdvance(total),5197);});
test("validates required customer fields",()=>{assert.equal(validCustomer(customer),true);assert.equal(validCustomer({...customer,address:""}),false);});
test("builds one-tap WhatsApp URL with order details",()=>{const url=whatsappOrderUrl("ORDER-1",customer,cart,cartTotal(cart));assert.match(url,/^https:\/\/wa\.me\/923238878009\?text=/);const text=decodeURIComponent(url.split("text=")[1]);assert.match(text,/Ali Raza/);assert.match(text,/Kashmiri Gold Bangles/);assert.match(text,/Rs 300 advance pending/);});
